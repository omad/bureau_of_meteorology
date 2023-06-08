"""Platform for sensor integration."""
from __future__ import annotations

import logging
from datetime import datetime, tzinfo

import iso8601
import pytz
from homeassistant.components.weather import WeatherEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SPEED_KILOMETERS_PER_HOUR, TEMP_CELSIUS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pytz import timezone

from . import BomDataUpdateCoordinator
from .const import (
    ATTRIBUTION,
    COLLECTOR,
    CONF_WEATHER_NAME,
    COORDINATOR,
    DOMAIN,
    MAP_CONDITION,
    MAP_NIGHT_CONDITION,
    SHORT_ATTRIBUTION,
    MODEL_NAME,
)
from .PyBoM.collector import Collector

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    hass_data = hass.data[DOMAIN][config_entry.entry_id]

    new_entities = []

    location_name = config_entry.options.get(
        CONF_WEATHER_NAME, config_entry.data.get(CONF_WEATHER_NAME, "Home")
    )

    new_entities.append(WeatherDaily(hass_data, location_name))
    new_entities.append(WeatherHourly(hass_data, location_name))

    if new_entities:
        async_add_entities(new_entities, update_before_add=False)


def condition_from_bom_hourly_forecast(forecast_data):
    # The hourly weather icon_descriptor indicates (at least sometimes)
    # 'sunny' + is_night=true, when it's going to be a clear night.
    icon_descriptor = forecast_data["icon_descriptor"]
    if forecast_data["is_night"]:
        icon_descriptor = MAP_NIGHT_CONDITION[icon_descriptor]
    return MAP_CONDITION[icon_descriptor]


class WeatherBase(WeatherEntity):
    """Base representation of a BOM weather entity."""

    def __init__(self, hass_data, location_name) -> None:
        """Initialize the sensor."""
        self.collector: Collector = hass_data[COLLECTOR]
        self.coordinator: BomDataUpdateCoordinator = hass_data[COORDINATOR]
        self.location_name: str = location_name
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self.location_name)},
            manufacturer=SHORT_ATTRIBUTION,
            model=MODEL_NAME,
            name=self.location_name,
        )

    async def async_added_to_hass(self) -> None:
        """Set up a listener and load data."""
        self.async_on_remove(self.coordinator.async_add_listener(self._update_callback))
        self.async_on_remove(self.coordinator.async_add_listener(self._update_callback))
        self._update_callback()

    @callback
    def _update_callback(self) -> None:
        """Load data from integration."""
        self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        """Entities do not individually poll."""
        return False

    @property
    def native_temperature(self):
        """Return the platform temperature."""
        return self.collector.observations_data["data"]["temp"]

    @property
    def icon(self):
        """Return the icon."""
        return self.collector.daily_forecasts_data["data"][0]["mdi_icon"]

    @property
    def native_temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    @property
    def humidity(self):
        """Return the humidity."""
        return self.collector.observations_data["data"]["humidity"]

    @property
    def native_wind_speed(self):
        """Return the wind speed."""
        return self.collector.observations_data["data"]["wind_speed_kilometre"]

    @property
    def native_wind_speed_unit(self):
        """Return the unit of measurement for wind speed."""
        return SPEED_KILOMETERS_PER_HOUR

    @property
    def wind_bearing(self):
        """Return the wind bearing."""
        return self.collector.observations_data["data"]["wind_direction"]

    @property
    def attribution(self):
        """Return the attribution."""
        return ATTRIBUTION

    @property
    def condition(self):
        """Return the current condition."""
        return condition_from_bom_hourly_forecast(self.collector.hourly_forecasts_data[0])

    async def async_update(self):
        await self.coordinator.async_update()


class WeatherDaily(WeatherBase):
    """Representation of a BOM weather entity."""

    def __init__(self, hass_data, location_name):
        """Initialize the sensor."""
        super().__init__(hass_data, location_name)

    @property
    def name(self):
        """Return the name."""
        return self.location_name

    @property
    def unique_id(self):
        """Return Unique ID string."""
        return self.location_name

    @property
    def forecast(self):
        """Return the forecast."""
        forecasts = []
        forecasts_data: list = self.collector.daily_forecasts_data["data"]
        tzinfo = pytz.timezone(self.collector.locations_data["data"]["timezone"])
        for day_data in forecasts_data:
            forecast = {
                "datetime": iso8601.parse_date(day_data["date"]).astimezone(tzinfo).isoformat(),
                "native_temperature": day_data["temp_max"],
                "condition": MAP_CONDITION[day_data["icon_descriptor"]],
                "templow": day_data["temp_min"],
                "native_precipitation": day_data["rain_amount_max"],
                "precipitation_probability": day_data["rain_chance"],
            }
            forecasts.append(forecast)
        return forecasts


class WeatherHourly(WeatherBase):
    """Representation of a BOM hourly weather entity."""

    def __init__(self, hass_data, location_name):
        """Initialize the sensor."""
        super().__init__(hass_data, location_name)

    @property
    def name(self):
        """Return the name."""
        return self.location_name + " Hourly"

    @property
    def unique_id(self):
        """Return Unique ID string."""
        return self.location_name + "_hourly"

    @property
    def forecast(self):
        """Return the forecast."""
        forecasts = []
        tzinfo = pytz.timezone(self.collector.locations_data["data"]["timezone"])
        hours = self.collector.hourly_forecasts_data["data"]
        for hour_data in hours:
            forecast = {
                "datetime": iso8601.parse_date(hour_data["time"]).astimezone(tzinfo).isoformat(),
                "native_temperature": hour_data["temp"],
                "condition": condition_from_bom_hourly_forecast(hour_data),
                "native_precipitation": hour_data["rain_amount_max"],
                "precipitation_probability": hour_data["rain_chance"],
                "wind_bearing": hour_data["wind_direction"],
                "native_wind_speed": hour_data["wind_speed_kilometre"],
                "wind_gust_speed": hour_data["wind_gust_speed_kilometre"],
                "humidity": hour_data["relative_humidity"],
                "uv": hour_data["uv"],
            }
            forecasts.append(forecast)
        return forecasts
