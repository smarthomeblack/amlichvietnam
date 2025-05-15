from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import STATE_UNKNOWN
from .amlich_core import query_date
import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "amlich"
INPUT_TEXT_ENTITY = "input_text.tracuu"

async def async_setup_platform(hass: HomeAssistant, config, async_add_entities: AddEntitiesCallback, discovery_info=None):
    """Thiết lập sensor."""
    _LOGGER.debug("Bắt đầu khởi tạo sensor.tra_cuu_su_kien")
    try:
        sensor = AmlichSensor(hass)
        async_add_entities([sensor])
        _LOGGER.info("Đã thêm sensor.tra_cuu_su_kien vào Home Assistant")
    except Exception as e:
        _LOGGER.error(f"Lỗi khi khởi tạo sensor.tra_cuu_su_kien: {str(e)}")
        raise

class AmlichSensor(SensorEntity):
    """Sensor tra cứu sự kiện."""

    def __init__(self, hass: HomeAssistant):
        self._hass = hass
        self._state = "Không có dữ liệu"
        self._attributes = {
            "output": "Không có dữ liệu",
            "is_lunar": False,
            "lunar_date": None,  # Lưu ngày âm lịch dạng DD/MM/YYYY
            "events": []
        }
        self._attr_name = "Tra Cứu Sự Kiện"
        self._attr_unique_id = f"{DOMAIN}_su_kien_sensor"
        self._attr_should_poll = False
        _LOGGER.debug("Đã khởi tạo instance AmlichSensor")

    async def async_added_to_hass(self):
        """Gọi khi sensor được thêm vào Home Assistant."""
        _LOGGER.debug("Gọi async_added_to_hass cho sensor.tra_cuu_su_kien")
        try:
            @callback
            def input_text_changed(event):
                new_state = event.data.get("new_state")
                if new_state is None or new_state.state == STATE_UNKNOWN:
                    return
                query = new_state.state.strip()
                if query:
                    _LOGGER.debug(f"Xử lý truy vấn: {query}")
                    async def handle_query():
                        result = await query_date(self._hass, query, use_humor=False)
                        self._attributes = {
                            "output": result.get("output", "Không có dữ liệu"),
                            "date": result.get("date"),
                            "range": result.get("range"),
                            "is_lunar": result.get("is_lunar", False),
                            "lunar_date": result.get("lunar_date"),  # Đảm bảo chứa năm (DD/MM/YYYY)
                            "events": result.get("events", [])
                        }
                        self._state = result.get("output", "Không có dữ liệu")[:255]
                        self.async_write_ha_state()
                    self._hass.async_create_task(handle_query())

            async_track_state_change_event(
                self._hass, [INPUT_TEXT_ENTITY], input_text_changed
            )
            _LOGGER.debug(f"Đã đăng ký lắng nghe {INPUT_TEXT_ENTITY}")

            input_state = self._hass.states.get(INPUT_TEXT_ENTITY)
            if input_state and input_state.state and input_state.state != STATE_UNKNOWN:
                result = await query_date(self._hass, input_state.state.strip(), use_humor=False)
                self._attributes = {
                    "output": result.get("output", "Không có dữ liệu"),
                    "date": result.get("date"),
                    "range": result.get("range"),
                    "is_lunar": result.get("is_lunar", False),
                    "lunar_date": result.get("lunar_date"),  # Đảm bảo chứa năm (DD/MM/YYYY)
                    "events": result.get("events", [])
                }
                self._state = result.get("output", "Không có dữ liệu")[:255]
                self.async_write_ha_state()
                _LOGGER.debug("Đã cập nhật state ban đầu cho sensor.tra_cuu_su_kien")
        except Exception as e:
            _LOGGER.error(f"Lỗi trong async_added_to_hass: {str(e)}")

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes