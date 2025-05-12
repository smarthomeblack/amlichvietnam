import os
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_PATH
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
import logging
import traceback
import asyncio

_LOGGER = logging.getLogger(__name__)

DOMAIN = "amlich"

CONFIG_SCHEMA = vol.Schema({
    vol.Required(DOMAIN): vol.Schema({
        vol.Required(CONF_PATH): cv.string,
        vol.Optional('api_key', default=""): cv.string,
    })
}, extra=vol.ALLOW_EXTRA)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Thiết lập component."""
    _LOGGER.debug("Bắt đầu thiết lập component amlich")
    try:
        # Kiểm tra cấu hình
        if DOMAIN not in config:
            _LOGGER.warning("Không tìm thấy cấu hình amlich trong configuration.yaml")
            return True

        conf = config[DOMAIN]
        ics_path = conf.get(CONF_PATH)
        api_key = conf.get('api_key')
        _LOGGER.debug(f"Cấu hình: ics_path={ics_path}, api_key={'****' if api_key else 'None'}")

        # Kiểm tra đường dẫn ICS
        if not ics_path:
            _LOGGER.error("Đường dẫn ICS không được cung cấp")
            return False

        # Kiểm tra file tồn tại và quyền (chạy trong executor)
        def check_file():
            try:
                if not os.path.exists(ics_path):
                    _LOGGER.error(f"File ICS không tồn tại: {ics_path}")
                    return False
                if not os.path.isfile(ics_path):
                    _LOGGER.error(f"Đường dẫn ICS không phải file: {ics_path}")
                    return False
                with open(ics_path, 'r', encoding='utf-8') as f:
                    content = f.read(1024)
                    if not content.strip():
                        _LOGGER.error(f"File ICS rỗng: {ics_path}")
                        return False
                size = os.path.getsize(ics_path)
                _LOGGER.debug(f"File ICS {ics_path} có thể đọc, kích thước: {size} bytes")
                return True
            except Exception as e:
                _LOGGER.error(f"Lỗi khi kiểm tra file ICS {ics_path}: {str(e)}")
                return False

        if not await hass.async_add_executor_job(check_file):
            return False

        # Lưu cấu hình
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN] = {'ics_path': ics_path, 'api_key': api_key}
        _LOGGER.debug("Đã lưu cấu hình vào hass.data")

        # Kiểm tra import amlich_core
        try:
            from .amlich_core import load_ics_file, set_api_key
        except ImportError as e:
            _LOGGER.error(f"Lỗi import amlich_core: {str(e)}")
            return False

        # Đặt API key
        try:
            await hass.async_add_executor_job(set_api_key, api_key)
            _LOGGER.debug("Đã đặt API key")
        except Exception as e:
            _LOGGER.error(f"Lỗi khi đặt API key: {str(e)}")
            return False

        # Tải file ICS
        try:
            if not await hass.async_add_executor_job(load_ics_file, ics_path):
                _LOGGER.error("Không thể tải file ICS")
                return False
            _LOGGER.debug("Đã tải file ICS thành công")
        except Exception as e:
            _LOGGER.error(f"Lỗi khi tải file ICS: {str(e)}")
            return False

        # Kích hoạt platform sensor
        try:
            hass.async_create_task(
                hass.config_entries.async_forward_entry_setup(
                    config[DOMAIN], "sensor"
                )
            )
            _LOGGER.debug("Đã yêu cầu thiết lập platform sensor")
        except Exception as e:
            _LOGGER.error(f"Lỗi khi thiết lập platform sensor: {str(e)}")
            return False

        # Đăng ký service reload_ics
        async def reload_ics_service(call):
            _LOGGER.debug("Gọi service reload_ics")
            try:
                if not await hass.async_add_executor_job(load_ics_file, ics_path):
                    _LOGGER.error("Không thể làm mới dữ liệu ICS")
                    return
                _LOGGER.debug("Đã làm mới dữ liệu ICS")
                sensor_entity_id = "sensor.tra_cuu_su_kien"
                if sensor_entity_id in hass.states.async_entity_ids():
                    await hass.helpers.entity_component.async_update_entity(sensor_entity_id)
                    _LOGGER.debug(f"Đã cập nhật sensor {sensor_entity_id}")
                else:
                    _LOGGER.warning(f"Sensor {sensor_entity_id} chưa được khởi tạo")
            except Exception as e:
                _LOGGER.error(f"Lỗi khi thực thi reload_ics: {str(e)}")
                raise

        hass.services.async_register(DOMAIN, "reload_ics", reload_ics_service)
        _LOGGER.debug("Đã đăng ký service reload_ics")

        _LOGGER.info("Thiết lập component amlich thành công")
        return True

    except Exception as e:
        _LOGGER.error(f"Lỗi nghiêm trọng khi thiết lập amlich: {str(e)}")
        _LOGGER.error(f"Traceback: {traceback.format_exc()}")
        return False