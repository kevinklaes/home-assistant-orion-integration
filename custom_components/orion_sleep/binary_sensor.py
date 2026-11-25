"""Binary sensor platform for Orion Sleep."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import OrionDataUpdateCoordinator
from .entity import OrionBaseEntity
from .faults import with_error_names
from .hub_health import (
    HubHealth,
    device_problem_attributes,
    device_problem_is_on,
    pad_sensor_problem_attributes,
    update_in_progress_attributes,
)

_LOGGER = logging.getLogger(__name__)


# Sensors exposed on every ``live_device.{snapshot,update}`` payload.
# Mapping to zone_a/zone_b isn't verified yet; we expose the raw names
# the server uses so the user can build their own side mapping.
_TOPPER_SENSORS: tuple[str, ...] = ("sensor1", "sensor2")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Orion Sleep binary sensor entities."""
    coordinator: OrionDataUpdateCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []

    for device in coordinator.devices:
        device_id = device.get("id")
        if not device_id:
            continue
        entities.append(OrionSessionActiveBinarySensor(coordinator, device_id))
        # Partner (second-side) parity — the partner's own session-active
        # state. Only created when a partner account is linked.
        if coordinator.has_partner:
            entities.append(
                OrionSessionActiveBinarySensor(
                    coordinator, device_id, is_partner=True
                )
            )
        for sensor_name in _TOPPER_SENSORS:
            entities.append(
                OrionSensorOnBedBinarySensor(coordinator, device_id, sensor_name)
            )

        entities.append(OrionProblemBinarySensor(coordinator, device_id))

        # Hub health: once per device (it belongs to the hub, not a user),
        # so never duplicated for a partner account.
        for description in HUB_HEALTH_BINARY_SENSORS:
            entities.append(
                OrionHubHealthBinarySensor(coordinator, device_id, description)
            )
        for sensor_name in _TOPPER_SENSORS:
            entities.append(
                OrionPadSensorProblemBinarySensor(coordinator, device_id, sensor_name)
            )

    async_add_entities(entities)


class OrionSessionActiveBinarySensor(OrionBaseEntity, BinarySensorEntity):
    """Binary sensor indicating if a sleep session is active.

    Determined by checking if the latest session in insights has
    is_in_progress == True.

    We intentionally do NOT set a device_class here. Using
    BinarySensorDeviceClass.RUNNING shows "Running / Not running" which
    is confusing for sleep tracking. Instead we rely on translation_key
    to provide "Asleep / Not asleep" state labels.
    """

    _attr_icon = "mdi:bed"

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
        is_partner: bool = False,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._is_partner = is_partner
        if is_partner:
            self._attr_translation_key = "partner_sleep_session_active"
            self._attr_unique_id = f"{device_id}_partner_session_active"
        else:
            self._attr_translation_key = "sleep_session_active"
            self._attr_unique_id = f"{device_id}_session_active"

    @property
    def is_on(self) -> bool | None:
        """Return True if a sleep session is currently active."""
        session = (
            self.coordinator.get_partner_latest_session()
            if self._is_partner
            else self.coordinator.get_latest_session()
        )
        if not session:
            return False
        return session.get("is_in_progress", False)


class OrionSensorOnBedBinarySensor(OrionBaseEntity, BinarySensorEntity):
    """Per-topper-sensor occupancy detector.

    Drives off the WebSocket ``status.sensors.<sensor_name>.status_text``
    field: ``"left_bed"`` means empty, any other value (observed:
    ``"normal"``) means the sensor detects a person.

    The WS frames themselves arrive in realtime, but the topper's own
    classification of on-bed vs. left-bed is slow: observed latency is
    roughly 30 s to 1 minute after sitting down or getting up before
    ``status_text`` transitions. Heart-rate/breath-rate updates are
    faster since those come straight off the sensor.

    The two sensors (``sensor1`` / ``sensor2``) correspond to the two
    measurement pads in the topper. Their mapping to ``zone_a`` /
    ``zone_b`` has not been verified against a split-occupancy capture,
    so entities are named per sensor rather than per side.
    """

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:bed-outline"

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
        sensor_name: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._sensor_name = sensor_name
        self._attr_translation_key = f"{sensor_name}_on_bed"
        self._attr_unique_id = f"{device_id}_{sensor_name}_on_bed"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.sensor_is_on_bed(self._device_id, self._sensor_name)

    @property
    def available(self) -> bool:
        # Report available whenever we have a live payload at all,
        # even if the individual sensor hasn't reported yet.
        return (
            self.coordinator.sensor_status_text(self._device_id, self._sensor_name)
            is not None
        )


class OrionProblemBinarySensor(OrionBaseEntity, BinarySensorEntity):
    """Diagnostic sensor that fires when the device reports a safety error."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "device_problem"

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_problem"

    @property
    def is_on(self) -> bool | None:
        return device_problem_is_on(
            self.coordinator.live_devices.get(self._device_id)
        )

    @property
    def extra_state_attributes(self) -> dict | None:
        # error_codes (unchanged), Orion's own error_descriptions, and
        # error_names (one fault name per code, from faults.py).
        return with_error_names(
            device_problem_attributes(
                self.coordinator.live_devices.get(self._device_id)
            )
        )


# ── Hub health (diagnostic) ───────────────────────────────────────────────
#
# Values come from coordinator.hub_health(), which parses the live payload
# in hub_health.py. These classes hold no parsing logic and do not override
# ``available``: a missing value shows as unknown.


@dataclass(frozen=True, kw_only=True)
class OrionHubBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a hub-health binary sensor read from a ``HubHealth`` snapshot."""

    value_fn: Callable[[HubHealth], bool | None]
    attrs_fn: Callable[[HubHealth], dict[str, Any] | None] | None = None


HUB_HEALTH_BINARY_SENSORS: tuple[OrionHubBinarySensorDescription, ...] = (
    OrionHubBinarySensorDescription(
        key="hub_online",
        translation_key="hub_online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda health: health.online,
    ),
    OrionHubBinarySensorDescription(
        key="firmware_update_available",
        translation_key="firmware_update_available",
        device_class=BinarySensorDeviceClass.UPDATE,
        value_fn=lambda health: health.update_available,
    ),
    OrionHubBinarySensorDescription(
        key="firmware_update_in_progress",
        translation_key="firmware_update_in_progress",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda health: health.update_in_progress,
        attrs_fn=update_in_progress_attributes,
    ),
    OrionHubBinarySensorDescription(
        key="water_fill_mode",
        translation_key="water_fill_mode",
        icon="mdi:water-plus",
        value_fn=lambda health: health.water_fill_mode,
    ),
)


class OrionHubHealthBinarySensor(OrionBaseEntity, BinarySensorEntity):
    """Diagnostic hub-health binary sensor driven by a description."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: OrionHubBinarySensorDescription

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
        description: OrionHubBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(
            self.coordinator.hub_health(self._device_id)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(
            self.coordinator.hub_health(self._device_id)
        )


class OrionPadSensorProblemBinarySensor(OrionBaseEntity, BinarySensorEntity):
    """On when a topper sensor pad reports ``is_working: false``."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
        sensor_name: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._sensor_name = sensor_name
        self._attr_translation_key = f"{sensor_name}_problem"
        self._attr_unique_id = f"{device_id}_{sensor_name}_problem"

    @property
    def is_on(self) -> bool | None:
        health = self.coordinator.hub_health(self._device_id)
        return health.pad_sensor(self._sensor_name).problem

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        health = self.coordinator.hub_health(self._device_id)
        return pad_sensor_problem_attributes(health.pad_sensor(self._sensor_name))
