import re
import json
import requests
from datetime import datetime, timedelta
from dateutil.parser import parse
from icalendar import Calendar
import logging
import os
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

GEMINI_API_KEY = None
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def set_api_key(api_key):
    global GEMINI_API_KEY
    GEMINI_API_KEY = api_key
    _LOGGER.debug(f"Đã đặt Gemini API key: {'***' if api_key else 'None'}")

_lunar_dates = {}
_solar_dates = {}
_events = {}

def load_ics_file(file_path):
    global _lunar_dates, _solar_dates, _events
    _lunar_dates = {}
    _solar_dates = {}
    _events = {}
    _LOGGER.debug(f"Đang tải file ICS từ: {file_path}")
    try:
        if not os.path.isfile(file_path):
            _LOGGER.error(f"File ICS không tồn tại hoặc không phải file: {file_path}")
            return False
        with open(file_path, 'r', encoding='utf-8') as f:
            _LOGGER.debug("Đang đọc nội dung file ICS")
            ics_content = f.read()
            if not ics_content.strip():
                _LOGGER.error("File ICS rỗng")
                return False
            cal = Calendar.from_ical(ics_content)
            _LOGGER.debug("Đã phân tích file ICS thành công")
            for event in cal.walk('VEVENT'):
                start_date = event.get('DTSTART').dt
                summary = event.get('SUMMARY')
                _LOGGER.debug(f"Processing event: DTSTART={start_date}, SUMMARY={summary}")
                if isinstance(start_date, datetime):
                    start_date = start_date.date()
                if re.match(r'^\d{1,2}/\d{1,2}(?:\s*\(N\))?$', summary):
                    lunar_date = summary.replace('(N)', '').strip()
                    try:
                        day, month = map(int, lunar_date.split('/'))
                        if not (1 <= day <= 31 and 1 <= month <= 12):
                            _LOGGER.error(f"Invalid lunar date format: {lunar_date}")
                            continue
                        lunar_date = f"{day:02d}/{month:02d}"
                        if start_date in _lunar_dates:
                            _LOGGER.error(f"Duplicate lunar date for {start_date}: existing={_lunar_dates[start_date]}, new={lunar_date}")
                            continue
                        _lunar_dates[start_date] = lunar_date
                        if lunar_date not in _solar_dates:
                            _solar_dates[lunar_date] = []
                        _solar_dates[lunar_date].append(start_date)
                        _LOGGER.debug(f"Mapped lunar date {lunar_date} → solar date {start_date.strftime('%Y-%m-%d')}")
                    except ValueError:
                        _LOGGER.error(f"Invalid lunar date format: {lunar_date}")
                        continue
                else:
                    if start_date not in _events:
                        _events[start_date] = []
                    _events[start_date].append(summary)
                    _LOGGER.debug(f"Added event for {start_date}: {summary}")
            _LOGGER.info(f"Đã tải {len(_lunar_dates)} ngày âm lịch, "
                         f"{len(_solar_dates)} ánh xạ âm lịch-dương lịch, "
                         f"{sum(len(e) for e in _events.values())} sự kiện")
            date_obj = datetime.strptime('2025-05-15', '%Y-%m-%d').date()
            if date_obj in _lunar_dates:
                _LOGGER.debug(f"_lunar_dates[2025-05-15]: {_lunar_dates[date_obj]}")
            return True
    except UnicodeDecodeError as e:
        _LOGGER.error(f"Lỗi mã hóa khi đọc file ICS: {str(e)}")
        return False
    except ValueError as e:
        _LOGGER.error(f"Lỗi định dạng ICS không hợp lệ: {str(e)}")
        return False
    except Exception as e:
        _LOGGER.error(f"Lỗi không xác định khi tải file ICS: {str(e)}")
        return False

def get_lunar_year(solar_date, lunar_dates):
    _LOGGER.debug(f"Determining lunar year for solar date: {solar_date}")
    year = solar_date.year
    for offset in [0, -1]:
        check_year = year + offset
        lunar_new_year_key = '01/01'
        new_year_dates = []
        for date, lunar in lunar_dates.items():
            if lunar == lunar_new_year_key and date.year == check_year:
                new_year_dates.append(date)
        for new_year_date in sorted(new_year_dates):
            _LOGGER.debug(f"Found lunar new year: {new_year_date}")
            if solar_date < new_year_date:
                lunar_year = check_year - 1
            else:
                lunar_year = check_year
            _LOGGER.debug(f"Lunar year for {solar_date}: {lunar_year}")
            return lunar_year
    _LOGGER.debug(f"No lunar new year found, defaulting to {year}")
    return year

def normalize_numbers_and_days(input_text):
    _LOGGER.debug(f"Normalizing numbers and days: {input_text}")
    number_map = {
        '1': 'một', '2': 'hai', '3': 'ba', '4': 'bốn', '4': 'tư', '5': 'năm',
        '6': 'sáu', '7': 'bảy', '8': 'tám', '9': 'chín', '10': 'mười',
        'cn': 'chủ nhật', 'chủ nhật': 'chủ nhật'
    }
    for key, value in number_map.items():
        pattern = rf'(?<!\d[/-])(?<!\d)\: {key}\b(?![/-]\d)'
        input_text = re.sub(pattern, value, input_text, flags=re.IGNORECASE)
    _LOGGER.debug(f"Normalized to: {input_text}")
    return input_text

def normalize_weekday(input_text):
    _LOGGER.debug(f"Normalizing weekday: {input_text}")
    weekday_map = {
        'thứ 2': 'thứ hai',
        'thứ hai': 'thứ hai',
        'thứ Hai': 'thứ hai',
        'thứ 3': 'thứ ba',
        'thứ ba': 'thứ ba',
        'thứ Ba': 'thứ ba',
        'thứ 4': 'thứ tư',
        'thứ tư': 'thứ tư',
        'thứ Tư': 'thứ tư',
        'thứ 5': 'thứ năm',
        'thứ năm': 'thứ năm',
        'thứ Năm': 'thứ năm',
        'thứ 6': 'thứ sáu',
        'thứ sáu': 'thứ sáu',
        'thứ Sáu': 'thứ sáu',
        'thứ 7': 'thứ bảy',
        'thứ bảy': 'thứ bảy',
        'thứ Bảy': 'thứ bảy',
        'chủ nhật': 'chủ nhật',
        'Chủ nhật': 'chủ nhật'
    }
    for key, value in weekday_map.items():
        if input_text.lower().startswith(key):
            normalized = input_text.lower().replace(key, value, 1)
            _LOGGER.debug(f"Normalized {input_text} to {normalized}")
            return normalized
    return input_text

async def fix_spelling(hass: HomeAssistant, input_text):
    if not GEMINI_API_KEY:
        _LOGGER.error("Không có Gemini API key được cấu hình")
        return input_text
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    prompt = f"""Sửa lỗi chính tả trong câu tiếng Việt sau, giữ nguyên ý nghĩa gốc và trả về chỉ câu đã sửa:
- Xử lý các lỗi như lặp chữ, sai dấu, sai từ.
- Không sửa các từ số (một, hai, ba,...) hoặc ngày (chủ nhật, cn).
- Không sửa định dạng ngày như '1/2', '01/02'.
- Chuẩn hóa các thứ: 'thứ 2' → 'thứ Hai', 'thu nam' → 'thứ Năm', v.v.
- Chuẩn hóa 'sự kien' → 'sự kiện'.
- Ví dụ:
  - 'tuaann nay' → 'tuần này'
  - 'thứ 2' → 'thứ Hai'
  - 'am lich hom nay' → 'âm lịch hôm nay'
  - 'sự kien' → 'sự kiện'
  - 'sự kien tháng 1' → 'sự kiện tháng 1'
  - 'sự kiện 1/2' → 'sự kiện 1/2'
- Không thêm giải thích, chỉ trả về câu đã sửa.

Input: '{input_text}'"""
    
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "response_mime_type": "text/plain"
        }
    }
    
    def make_request():
        try:
            response = requests.post(GEMINI_API_URL, headers=headers, json=data)
            _LOGGER.debug(f"Sửa lỗi chính tả - Status code: {response.status_code}")
            if response.status_code == 200:
                fixed_text = response.json()['candidates'][0]['content']['parts'][0]['text'].strip()
                _LOGGER.debug(f"Input gốc: '{input_text}' → Input sửa: '{fixed_text}'")
                return fixed_text
            else:
                _LOGGER.error(f"Lỗi sửa lỗi chính tả: {response.status_code} - {response.text}")
                return input_text
        except Exception as e:
            _LOGGER.error(f"Lỗi khi sửa lỗi chính tả: {str(e)}")
            return input_text

    return await hass.async_add_executor_job(make_request)

async def parse_with_gemini(hass: HomeAssistant, input_text):
    if not GEMINI_API_KEY:
        _LOGGER.error("Không có Gemini API key được cấu hình")
        return {'error': 'Không có Gemini API key'}
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    current_date = datetime.now().date()
    current_year = current_date.year
    prompt = f"""Hôm nay là {current_date.strftime('%Y-%m-%d')}. Hãy phân tích input sau và trả về JSON theo định dạng:
- Nếu là ngày cụ thể: {{"date": "YYYY-MM-DD"}}
- Nếu là khoảng thời gian: {{"range": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}}}
- Nếu không xác định được ngày, trả về: {{"error": "Không thể xác định ngày"}}.
- Không trả về date hoặc range là null. Không thêm các trường is_event, is_lunar, is_solar.
- Luôn trả về JSON hợp lệ.

Hướng dẫn:
1. Các tháng bằng chữ tiếng Việt: 'sáu' là tháng 6, 'bảy' là tháng 7, v.v.
2. Các cụm thời gian:
   - 'ngày này tuần sau': ngày hiện tại cộng 7 ngày.
   - 'ngày này tháng sau': ngày hiện tại trong tháng sau.
   - 'tuần này': từ thứ Hai đến Chủ Nhật của tuần hiện tại.
   - 'tháng sáu': từ ngày 1 đến ngày cuối của tháng 6 năm {current_year}.
3. Nếu không có năm, sử dụng năm hiện tại ({current_year}).
4. Định dạng ngày như '1/2' hiểu là ngày 1 tháng 2 năm {current_year}.

Ví dụ:
- Input: 'ngày này tuần sau' → {{"date": "2025-05-22"}}
- Input: 'tuần này' → {{"range": {{"start": "2025-05-12", "end": "2025-05-18"}}}}
- Input: 'tháng sáu' → {{"range": {{"start": "2025-06-01", "end": "2025-06-30"}}}}
- Input: '1/2' → {{"date": "2025-02-01"}}
Input: '{input_text}'"""
    
    _LOGGER.debug(f"Gọi Gemini AI với input: {input_text}")
    
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }
    
    def make_request():
        try:
            response = requests.post(GEMINI_API_URL, headers=headers, json=data)
            _LOGGER.debug(f"Status code từ Gemini API: {response.status_code}")
            if response.status_code == 200:
                response_json = response.json()
                if 'candidates' in response_json and response_json['candidates']:
                    response_text = response_json['candidates'][0]['content']['parts'][0]['text']
                    _LOGGER.debug(f"Response JSON từ Gemini AI: {response_text}")
                    result = json.loads(response_text)
                    if 'date' not in result and 'range' not in result and 'error' not in result:
                        _LOGGER.debug("Response từ Gemini thiếu date, range hoặc error")
                        return {'error': 'Response từ Gemini không hợp lệ'}
                    return result
                else:
                    _LOGGER.debug("Không tìm thấy 'candidates' trong response từ Gemini")
                    return {'error': 'Response từ Gemini AI không hợp lệ'}
            else:
                _LOGGER.debug(f"Lỗi Gemini API: {response.status_code} - {response.text}")
                return {'error': f'Lỗi khi gọi Gemini API: {response.status_code}'}
        except Exception as e:
            _LOGGER.debug(f"Lỗi khi gọi Gemini API: {str(e)}")
            return {'error': f'Lỗi kết nối Gemini API: {str(e)}'}

    return await hass.async_add_executor_job(make_request)

async def parse_input(hass: HomeAssistant, input_text, is_fixed=False):
    _LOGGER.debug(f"Parsing input: {input_text}, is_fixed={is_fixed}")
    original_input = input_text
    input_text = input_text.lower().strip()
    # Chuẩn hóa input để xử lý ký tự ẩn, khoảng trắng thừa
    input_text = re.sub(r'\s+', ' ', input_text).strip()
    is_event = 'sự kiện' in input_text.lower()
    input_text = normalize_numbers_and_days(input_text)
    input_text = normalize_weekday(input_text)
    today = datetime.now().date()
    _LOGGER.debug(f"Current date: {today}")

    is_lunar = 'âm lịch' in input_text
    is_solar = 'dương lịch' in input_text
    _LOGGER.debug(f"Initial flags: is_event={is_event}, is_lunar={is_lunar}, is_solar={is_solar}")
    date_part = input_text
    if is_event:
        date_part = date_part.replace('sự kiện', '', 1).strip()
        _LOGGER.debug(f"Removed 'sự kiện', date_part: {date_part}")
    if is_lunar:
        date_part = date_part.replace('âm lịch', '').strip()
        _LOGGER.debug(f"Removed 'âm lịch', date_part: {date_part}")
    if is_solar:
        date_part = date_part.replace('dương lịch', '').strip()
        _LOGGER.debug(f"Removed 'dương lịch', date_part: {date_part}")

    week_pattern = r'^(một|hai|ba|bốn|tư|năm|sáu|bảy|\d+)\s+tuần\s+(sau|tới)$'
    match = re.match(week_pattern, date_part)
    if match:
        num_str = match.group(1)
        num_dict = {'một': 1, 'hai': 2, 'ba': 3, 'bốn': 4, 'tư': 4, 'năm': 5, 'sáu': 6, 'bảy': 7}
        num = num_dict.get(num_str, int(num_str) if num_str.isdigit() else 0)
        if num == 0:
            _LOGGER.error(f"Invalid number: {num_str}")
            return {'error': f'Số không hợp lệ: {num_str}'}
        _LOGGER.debug(f"Week pattern matched - Number: {num}")
        start = today - timedelta(days=today.weekday()) + timedelta(days=7 * num)
        end = start + timedelta(days=6)
        _LOGGER.debug(f"Week range parsed - From: {start}, To: {end}")
        return {
            'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')},
            'is_event': is_event,
            'is_lunar': False,
            'is_solar': True
        }

    month_pattern = r'^(một|hai|ba|bốn|tư|năm|sáu|bảy|\d+)\s+tháng\s+(sau|tới)$'
    match = re.match(month_pattern, date_part)
    if match:
        num_str = match.group(1)
        num_dict = {'một': 1, 'hai': 2, 'ba': 3, 'bốn': 4, 'tư': 4, 'năm': 5, 'sáu': 6, 'bảy': 7}
        num = num_dict.get(num_str, int(num_str) if num_str.isdigit() else 0)
        if num == 0:
            _LOGGER.error(f"Invalid number: {num_str}")
            return {'error': f'Số không hợp lệ: {num_str}'}
        _LOGGER.debug(f"Month pattern matched - Number: {num}")
        start = (today.replace(day=1) + timedelta(days=31 * num)).replace(day=1)
        end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        _LOGGER.debug(f"Month range parsed - From: {start}, To: {end}")
        return {
            'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')},
            'is_event': is_event,
            'is_lunar': False,
            'is_solar': True
        }

    _LOGGER.debug(f"Checking exact matches for date_part: {date_part}")
    exact_matches = {
        'hôm nay': today,
        'hôm này': today,
        'ngày hôm nay': today,
        'ngày này': today,
        'hôm qua': today - timedelta(days=1),
        'hôm kia': today - timedelta(days=2),
        'ngày mai': today + timedelta(days=1),
        'hôm sau': today + timedelta(days=1),
        'ngày kia': today + timedelta(days=2),
        'ngày mốt': today + timedelta(days=2),
        'ngày này tuần sau': today + timedelta(days=7),
        'hôm nay tuần sau': today + timedelta(days=7)
    }
    if date_part in exact_matches:
        solar_date = exact_matches[date_part]
        _LOGGER.debug(f"Exact match found - Solar date: {solar_date}")
        if is_lunar:
            day, month = solar_date.day, solar_date.month
            lunar_date = f"{day:02d}/{month:02d}"
            lunar_year = get_lunar_year(solar_date, _lunar_dates)
            lunar_date_with_year = f"{lunar_date}/{lunar_year}"
            _LOGGER.debug(f"Assuming solar date {solar_date} as lunar date: {lunar_date_with_year}")
            if lunar_date in _solar_dates:
                solar_dates = sorted(_solar_dates[lunar_date])
                _LOGGER.debug(f"Solar dates for lunar {lunar_date}: {[d.strftime('%Y-%m-%d') for d in solar_dates]}")
                selected_solar_date = min(solar_dates, key=lambda d: abs((datetime(lunar_year, month, day).date() - d).days))
                _LOGGER.debug(f"Selected solar date: {selected_solar_date} for lunar {lunar_date_with_year}")
                return {
                    'date': selected_solar_date.strftime('%Y-%m-%d'),
                    'is_event': is_event,
                    'is_lunar': True,
                    'is_solar': False,
                    'lunar_date': lunar_date_with_year
                }
            else:
                _LOGGER.error(f"No solar dates found for lunar {lunar_date}")
                return {'error': f'Không tìm thấy ngày âm lịch {lunar_date} trong dữ liệu ICS'}
        else:
            return {
                'date': solar_date.strftime('%Y-%m-%d'),
                'is_event': is_event,
                'is_lunar': is_lunar,
                'is_solar': is_solar or (not is_lunar and not is_event)
            }

    _LOGGER.debug(f"Checking weekday matches for date_part: {date_part}")
    weekday_matches = {
        'thứ hai': 0,
        'thứ ba': 1,
        'thứ tư': 2,
        'thứ năm': 3,
        'thứ sáu': 4,
        'thứ bảy': 5,
        'chủ nhật': 6
    }
    week_modifiers = {
        'tuần này': 0,
        'tuần trước': -7,
        'tuần sau': 7,
        'tuần tới': 7
    }
    weekday_pattern = r'^(thứ\s*(?:hai|ba|tư|năm|sáu|bảy)|chủ nhật)(?:\s*(tuần\s*(?:này|trước|sau|tới)))?$'
    match = re.match(weekday_pattern, date_part)
    if match:
        weekday_str = match.group(1).strip()
        week_modifier_str = match.group(2) if match.group(2) else 'tuần này'
        _LOGGER.debug(f"Weekday parsed: {weekday_str}, week modifier: {week_modifier_str}")
        if weekday_str not in weekday_matches:
            return {'error': f'Thứ không hợp lệ: {weekday_str}'}
        weekday = weekday_matches[weekday_str]
        week_offset = week_modifiers[week_modifier_str]
        current_weekday = today.weekday()
        days_diff = weekday - current_weekday
        solar_date = today + timedelta(days=days_diff + week_offset)
        _LOGGER.debug(f"Calculated solar date: {solar_date}")
        if is_lunar:
            day, month = solar_date.day, solar_date.month
            lunar_date = f"{day:02d}/{month:02d}"
            lunar_year = get_lunar_year(solar_date, _lunar_dates)
            lunar_date_with_year = f"{lunar_date}/{lunar_year}"
            _LOGGER.debug(f"Assuming solar date {solar_date} as lunar date: {lunar_date_with_year}")
            if lunar_date in _solar_dates:
                solar_dates = sorted(_solar_dates[lunar_date])
                _LOGGER.debug(f"Solar dates for lunar {lunar_date}: {[d.strftime('%Y-%m-%d') for d in solar_dates]}")
                selected_solar_date = min(solar_dates, key=lambda d: abs((datetime(lunar_year, month, day).date() - d).days))
                _LOGGER.debug(f"Selected solar date: {selected_solar_date} for lunar {lunar_date_with_year}")
                return {
                    'date': selected_solar_date.strftime('%Y-%m-%d'),
                    'is_event': is_event,
                    'is_lunar': True,
                    'is_solar': False,
                    'lunar_date': lunar_date_with_year
                }
            else:
                _LOGGER.error(f"No solar dates found for lunar {lunar_date}")
                return {'error': f'Không tìm thấy ngày âm lịch {lunar_date} trong dữ liệu ICS'}
        else:
            return {
                'date': solar_date.strftime('%Y-%m-%d'),
                'is_event': is_event,
                'is_lunar': is_lunar,
                'is_solar': is_solar or (not is_lunar and not is_event)
            }

    if is_lunar:
        _LOGGER.debug(f"Processing lunar input: {date_part}")
        lunar_pattern = r'^(\d{1,2})[/-](\d{1,2})$'
        match = re.match(lunar_pattern, date_part)
        if match:
            day, month = map(int, match.groups()[:2])
            year = today.year
            lunar_date = f"{day:02d}/{month:02d}"
            lunar_date_with_year = f"{lunar_date}/{year}"
            _LOGGER.debug(f"Lunar input parsed: day={day}, month={month}, year={year}, normalized={lunar_date_with_year}")
            if lunar_date in _solar_dates:
                start_date = datetime(year, max(1, month - 3), 1).date()
                end_date = datetime(year, month + 3, 1).date() - timedelta(days=1)
                _LOGGER.debug(f"Search range: {start_date} to {end_date}")
                solar_dates = sorted([d for d in _solar_dates[lunar_date] if start_date <= d <= end_date])
                _LOGGER.debug(f"Solar dates for lunar {lunar_date}: {[d.strftime('%Y-%m-%d') for d in solar_dates]}")
                if solar_dates:
                    selected_solar_date = min(solar_dates, key=lambda d: abs((datetime(year, month, 1).date() - d).days))
                    _LOGGER.debug(f"Selected solar date: {selected_solar_date} for lunar {lunar_date_with_year}")
                    return {
                        'date': selected_solar_date.strftime('%Y-%m-%d'),
                        'is_event': is_event,
                        'is_lunar': True,
                        'is_solar': False,
                        'lunar_date': lunar_date_with_year
                    }
                else:
                    _LOGGER.error(f"No solar dates found for lunar {lunar_date} in range")
                    return {'error': f'Không tìm thấy ngày âm lịch {lunar_date} trong khoảng thời gian hợp lý'}
            else:
                _LOGGER.error(f"No lunar date {lunar_date} found in _solar_dates")
                return {'error': f'Không tìm thấy ngày âm lịch {lunar_date} trong dữ liệu ICS'}

    if date_part == 'ngày này tháng sau':
        solar_date = (today + timedelta(days=31)).replace(day=today.day)
        _LOGGER.debug(f"Parsed 'ngày này tháng sau' - Date: {solar_date}")
        if is_lunar:
            day, month = solar_date.day, solar_date.month
            lunar_date = f"{day:02d}/{month:02d}"
            lunar_year = get_lunar_year(solar_date, _lunar_dates)
            lunar_date_with_year = f"{lunar_date}/{lunar_year}"
            _LOGGER.debug(f"Assuming solar date {solar_date} as lunar date: {lunar_date_with_year}")
            if lunar_date in _solar_dates:
                solar_dates = sorted(_solar_dates[lunar_date])
                _LOGGER.debug(f"Solar dates for lunar {lunar_date}: {[d.strftime('%Y-%m-%d') for d in solar_dates]}")
                selected_solar_date = min(solar_dates, key=lambda d: abs((datetime(lunar_year, month, day).date() - d).days))
                _LOGGER.debug(f"Selected solar date: {selected_solar_date} for lunar {lunar_date_with_year}")
                return {
                    'date': selected_solar_date.strftime('%Y-%m-%d'),
                    'is_event': is_event,
                    'is_lunar': True,
                    'is_solar': False,
                    'lunar_date': lunar_date_with_year
                }
            else:
                _LOGGER.error(f"No solar dates found for lunar {lunar_date}")
                return {'error': f'Không tìm thấy ngày âm lịch {lunar_date} trong dữ liệu ICS'}
        else:
            return {
                'date': solar_date.strftime('%Y-%m-%d'),
                'is_event': is_event,
                'is_lunar': is_lunar,
                'is_solar': is_solar or (not is_lunar and not is_event)
            }

    _LOGGER.debug(f"Checking date patterns for: {date_part}")
    date_patterns = [
        r'^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$',
        r'^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$',
        r'^(\d{1,2})[/-](\d{1,2})$',
    ]
    for pattern in date_patterns:
        match = re.match(pattern, date_part)
        if match:
            day, month = map(int, match.groups()[:2])
            year = int(match.groups()[2]) if len(match.groups()) > 2 else today.year
            if len(str(year)) == 2:
                year = 2000 + year
            _LOGGER.debug(f"Date pattern matched - Day: {day}, Month: {month}, Year: {year}")
            try:
                solar_date = datetime(year, month, day).date()
                _LOGGER.debug(f"Parsed date: {solar_date}")
                if is_lunar:
                    day, month = solar_date.day, solar_date.month
                    lunar_date = f"{day:02d}/{month:02d}"
                    lunar_year = get_lunar_year(solar_date, _lunar_dates)
                    lunar_date_with_year = f"{lunar_date}/{lunar_year}"
                    _LOGGER.debug(f"Assuming solar date {solar_date} as lunar date: {lunar_date_with_year}")
                    if lunar_date in _solar_dates:
                        solar_dates = sorted(_solar_dates[lunar_date])
                        _LOGGER.debug(f"Solar dates for lunar {lunar_date}: {[d.strftime('%Y-%m-%d') for d in solar_dates]}")
                        selected_solar_date = min(solar_dates, key=lambda d: abs((datetime(lunar_year, month, day).date() - d).days))
                        _LOGGER.debug(f"Selected solar date: {selected_solar_date} for lunar {lunar_date_with_year}")
                        return {
                            'date': selected_solar_date.strftime('%Y-%m-%d'),
                            'is_event': is_event,
                            'is_lunar': True,
                            'is_solar': False,
                            'lunar_date': lunar_date_with_year
                        }
                    else:
                        _LOGGER.error(f"No solar dates found for lunar {lunar_date}")
                        return {'error': f'Không tìm thấy ngày âm lịch {lunar_date} trong dữ liệu ICS'}
                else:
                    return {
                        'date': solar_date.strftime('%Y-%m-%d'),
                        'is_event': is_event,
                        'is_lunar': is_lunar,
                        'is_solar': is_solar or (not is_lunar and not is_event)
                    }
            except ValueError:
                _LOGGER.debug(f"Invalid date: {day}/{month}/{year}")
                pass

    _LOGGER.debug(f"Checking text pattern for: {date_part}")
    text_pattern = r'^(?:ngày\s+)?(\d{1,2})\s+tháng\s+(\d{1,2})(?:\s+năm\s+(\d{2,4}))?$'
    match = re.match(text_pattern, date_part)
    if match:
        day, month = map(int, match.groups()[:2])
        year = int(match.groups()[2]) if match.groups()[2] else today.year
        if len(str(year)) == 2:
            year = 2000 + year
        _LOGGER.debug(f"Text pattern matched - Day: {day}, Month: {month}, Year: {year}")
        try:
            solar_date = datetime(year, month, day).date()
            _LOGGER.debug(f"Parsed date: {solar_date}")
            if is_lunar:
                day, month = solar_date.day, solar_date.month
                lunar_date = f"{day:02d}/{month:02d}"
                lunar_year = get_lunar_year(solar_date, _lunar_dates)
                lunar_date_with_year = f"{lunar_date}/{lunar_year}"
                _LOGGER.debug(f"Assuming solar date {solar_date} as lunar date: {lunar_date_with_year}")
                if lunar_date in _solar_dates:
                    solar_dates = sorted(_solar_dates[lunar_date])
                    _LOGGER.debug(f"Solar dates for lunar {lunar_date}: {[d.strftime('%Y-%m-%d') for d in solar_dates]}")
                    selected_solar_date = min(solar_dates, key=lambda d: abs((datetime(lunar_year, month, day).date() - d).days))
                    _LOGGER.debug(f"Selected solar date: {selected_solar_date} for lunar {lunar_date_with_year}")
                    return {
                        'date': selected_solar_date.strftime('%Y-%m-%d'),
                        'is_event': is_event,
                        'is_lunar': True,
                        'is_solar': False,
                        'lunar_date': lunar_date_with_year
                    }
                else:
                    _LOGGER.error(f"No solar dates found for lunar {lunar_date}")
                    return {'error': f'Không tìm thấy ngày âm lịch {lunar_date} trong dữ liệu ICS'}
            else:
                return {
                    'date': solar_date.strftime('%Y-%m-%d'),
                    'is_event': is_event,
                    'is_lunar': is_lunar,
                    'is_solar': is_solar or (not is_lunar and not is_event)
                }
        except ValueError:
            _LOGGER.debug(f"Invalid date: {day}/{month}/{year}")
            pass

    _LOGGER.debug(f"Checking month names for: {date_part}")
    month_names = {
        'một': 1, 'hai': 2, 'ba': 3, 'bốn': 4, 'tư': 4, 'năm': 5, 'sáu': 6,
        'bảy': 7, 'tám': 8, 'chín': 9, 'mười': 10, 'mười một': 11, 'mười hai': 12
    }
    month_pattern = r'^tháng\s+(.+)$'
    match = re.match(month_pattern, date_part)
    if match:
        month_name = match.group(1).strip()
        for name, num in month_names.items():
            if name == month_name:
                month = num
                start = today.replace(month=month, day=1)
                end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
                _LOGGER.debug(f"Month parsed - Month: {month}, Range: {start} to {end}")
                return {
                    'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')},
                    'is_event': is_event,
                    'is_lunar': is_lunar,
                    'is_solar': is_solar or (not is_lunar and not is_event)
                }

    _LOGGER.debug(f"Checking month number pattern for: {date_part}")
    month_num_pattern = r'^tháng\s+(\d{1,2})$'
    match = re.match(month_num_pattern, date_part)
    if match:
        month = int(match.group(1))
        if 1 <= month <= 12:
            start = today.replace(month=month, day=1)
            end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
            _LOGGER.debug(f"Month number parsed - Month: {month}, Range: {start} to {end}")
            return {
                'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')},
                'is_event': is_event,
                'is_lunar': is_lunar,
                'is_solar': is_solar or (not is_lunar and not is_event)
            }

    _LOGGER.debug(f"Checking range matches for: {date_part}")
    exact_range_matches = {
        'tuần này': (today - timedelta(days=today.weekday()), 6),
        'tuần trước': (today - timedelta(days=today.weekday() + 7), 6),
        'tuần sau': (today - timedelta(days=today.weekday()) + timedelta(days=7), 6),
        'tuần tới': (today - timedelta(days=today.weekday()) + timedelta(days=7), 6),
        'tháng này': (today.replace(day=1), None),
        'tháng sau': ((today.replace(day=1) + timedelta(days=31)).replace(day=1), None),
        'tháng tới': ((today.replace(day=1) + timedelta(days=31)).replace(day=1), None)
    }
    for key, (start, days) in exact_range_matches.items():
        if date_part == key:
            if days:
                end = start + timedelta(days=days)
            else:
                end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
            _LOGGER.debug(f"Range match parsed - From: {start}, To: {end}")
            return {
                'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')},
                'is_event': is_event,
                'is_lunar': is_lunar,
                'is_solar': is_solar or (not is_lunar and not is_event)
            }

    if not is_fixed:
        _LOGGER.debug(f"Local parse failed, trying to fix spelling for: {original_input}")
        fixed_input = await fix_spelling(hass, original_input)
        if fixed_input.lower() != original_input.lower():
            _LOGGER.debug(f"Retrying parse with fixed input: {fixed_input}")
            return await parse_input(hass, fixed_input, is_fixed=True)

    _LOGGER.debug(f"Local parse failed after fix, falling back to Gemini for: {date_part}")
    gemini_result = await parse_with_gemini(hass, date_part)
    gemini_result.update({
        'is_event': is_event,
        'is_lunar': is_lunar,
        'is_solar': is_solar or (not is_lunar and not is_event)
    })
    if 'date' in gemini_result and is_lunar:
        solar_date = datetime.strptime(gemini_result['date'], '%Y-%m-%d').date()
        day, month = solar_date.day, solar_date.month
        lunar_date = f"{day:02d}/{month:02d}"
        lunar_year = get_lunar_year(solar_date, _lunar_dates)
        lunar_date_with_year = f"{lunar_date}/{lunar_year}"
        _LOGGER.debug(f"Assuming solar date {solar_date} as lunar date: {lunar_date_with_year}")
        if lunar_date in _solar_dates:
            solar_dates = sorted(_solar_dates[lunar_date])
            _LOGGER.debug(f"Solar dates for lunar {lunar_date}: {[d.strftime('%Y-%m-%d') for d in solar_dates]}")
            selected_solar_date = min(solar_dates, key=lambda d: abs((datetime(lunar_year, month, day).date() - d).days))
            _LOGGER.debug(f"Selected solar date: {selected_solar_date} for lunar {lunar_date_with_year}")
            return {
                'date': selected_solar_date.strftime('%Y-%m-%d'),
                'is_event': is_event,
                'is_lunar': True,
                'is_solar': False,
                'lunar_date': lunar_date_with_year
            }
        else:
            _LOGGER.error(f"No solar dates found for lunar {lunar_date}")
            return {'error': f'Không tìm thấy ngày âm lịch {lunar_date} trong dữ liệu ICS'}
    return gemini_result

async def generate_humorous_output(hass: HomeAssistant, original_output, use_humor=True):
    if not use_humor:
        return original_output
    if not GEMINI_API_KEY:
        _LOGGER.error("Không có Gemini API key được cấu hình")
        return original_output
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    prompt = f"""Hãy viết lại đoạn văn sau với giọng điệu hài hước, dí dỏm, nhưng giữ nguyên thông tin chính xác:
'{original_output}'"""
    
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "response_mime_type": "text/plain"
        }
    }
    
    def make_request():
        try:
            response = requests.post(GEMINI_API_URL, headers=headers, json=data)
            if response.status_code == 200:
                humorous_text = response.json()['candidates'][0]['content']['parts'][0]['text']
                _LOGGER.debug(f"Humorous output generated: {humorous_text}")
                return humorous_text
            else:
                _LOGGER.error(f"Lỗi Gemini API (hài hước): {response.status_code} - {response.text}")
                return original_output
        except Exception as e:
            _LOGGER.error(f"Lỗi tạo output hài hước: {str(e)}")
            return original_output

    return await hass.async_add_executor_job(make_request)

async def query_date(hass: HomeAssistant, query, use_humor=True):
    global _lunar_dates, _solar_dates, _events
    _LOGGER.debug(f"Querying date for: {query}, use_humor={use_humor}")
    try:
        parsed = await parse_input(hass, query)
        _LOGGER.debug(f"Parsed result: {parsed}")
        if not parsed or 'error' in parsed:
            original_output = parsed.get('error', "Không thể phân tích input. Vui lòng thử lại!")
            _LOGGER.debug(f"Parse error: {original_output}")
            return {"output": await generate_humorous_output(hass, original_output, use_humor)}

        result = {}
        is_event = parsed.get('is_event', False)
        is_lunar = parsed.get('is_lunar', False)
        is_solar = parsed.get('is_solar', False)
        lunar_date = parsed.get('lunar_date', None)
        _LOGGER.debug(f"is_event={is_event}, is_lunar={is_lunar}, is_solar={is_solar}, lunar_date={lunar_date}")

        if 'date' in parsed and parsed['date']:
            try:
                date = datetime.strptime(parsed['date'], '%Y-%m-%d').date()
                weekday = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật'][date.weekday()]
                if is_lunar:
                    _LOGGER.debug(f"Processing lunar date: {lunar_date} for solar {date}")
                    if is_event:
                        event_list = _events.get(date, [])
                        _LOGGER.debug(f"Events for {date}: {event_list}")
                        if event_list:
                            events_str = ', '.join(event_list)
                            original_output = f"Âm lịch ngày {lunar_date} tương ứng với dương lịch {date.strftime('%d/%m/%Y')} ({weekday}) có sự kiện: {events_str}!"
                        else:
                            original_output = f"Âm lịch ngày {lunar_date} tương ứng với dương lịch {date.strftime('%d/%m/%Y')} ({weekday}) không có sự kiện nào!"
                    else:
                        original_output = f"Âm lịch ngày {lunar_date} tương ứng với dương lịch {date.strftime('%d/%m/%Y')} ({weekday})!"
                    _LOGGER.debug(f"Output for lunar date: {original_output}")
                    result = {
                        'date': date.strftime('%Y-%m-%d'),
                        'lunar_date': lunar_date,
                        'events': _events.get(date, []),
                        'is_lunar': True,
                        'is_solar': False,
                        'is_event': is_event,
                        'output': await generate_humorous_output(hass, original_output, use_humor)
                    }
                else:
                    actual_lunar_date = _lunar_dates.get(date, 'Không có dữ liệu âm lịch')
                    if actual_lunar_date != 'Không có dữ liệu âm lịch':
                        try:
                            day, month = map(int, actual_lunar_date.split('/'))
                            lunar_year = get_lunar_year(date, _lunar_dates)
                            actual_lunar_date = f"{day:02d}/{month:02d}/{lunar_year}"
                        except ValueError:
                            _LOGGER.error(f"Invalid lunar date format: {actual_lunar_date}")
                            actual_lunar_date = 'Dữ liệu âm lịch không hợp lệ'
                    _LOGGER.debug(f"Processing solar date: {date}, lunar: {actual_lunar_date}")
                    if is_event:
                        event_list = _events.get(date, [])
                        _LOGGER.debug(f"Events for {date}: {event_list}")
                        if event_list:
                            events_str = ', '.join(event_list)
                            original_output = f"Dương lịch ngày {date.strftime('%d/%m/%Y')} ({weekday}) có sự kiện: {events_str} (âm lịch {actual_lunar_date})!"
                        else:
                            original_output = f"Dương lịch ngày {date.strftime('%d/%m/%Y')} ({weekday}) không có sự kiện nào!"
                    else:
                        original_output = f"Dương lịch ngày {date.strftime('%d/%m/%Y')} ({weekday}) là ngày {actual_lunar_date} âm lịch!"
                    _LOGGER.debug(f"Output for solar date: {original_output}")
                    result = {
                        'date': date.strftime('%Y-%m-%d'),
                        'lunar_date': actual_lunar_date,
                        'events': _events.get(date, []),
                        'is_lunar': False,
                        'is_solar': is_solar or (not is_lunar and not is_event),
                        'is_event': is_event,
                        'output': await generate_humorous_output(hass, original_output, use_humor)
                    }
            except (ValueError, TypeError) as e:
                _LOGGER.debug(f"Error processing date: {e}")
                original_output = "Ngày không hợp lệ. Vui lòng kiểm tra lại!"
                return {"output": await generate_humorous_output(hass, original_output, use_humor)}
        elif 'range' in parsed:
            start = datetime.strptime(parsed['range']['start'], '%Y-%m-%d').date()
            end = datetime.strptime(parsed['range']['end'], '%Y-%m-%d').date()
            _LOGGER.debug(f"Processing range: {start} to {end}")
            event_list = []
            for d in (start + timedelta(n) for n in range((end - start).days + 1)):
                if d in _events:
                    for evt in _events[d]:
                        actual_lunar_date = _lunar_dates.get(d, 'Không có dữ liệu âm lịch')
                        if actual_lunar_date != 'Không có dữ liệu âm lịch':
                            try:
                                day, month = map(int, actual_lunar_date.split('/'))
                                lunar_year = get_lunar_year(d, _lunar_dates)
                                actual_lunar_date = f"{day:02d}/{month:02d}/{lunar_year}"
                            except ValueError:
                                _LOGGER.error(f"Invalid lunar date format: {actual_lunar_date}")
                                actual_lunar_date = 'Dữ liệu âm lịch không hợp lệ'
                        event_list.append(f"Ngày {d.strftime('%d/%m/%Y')} ({actual_lunar_date} âm lịch) là {evt}")
                        _LOGGER.debug(f"Event found for {d}: {evt}")
            if is_event:
                if event_list:
                    original_output = f"Trong khoảng từ {start.strftime('%d/%m/%Y')} đến {end.strftime('%d/%m/%Y')} có {len(event_list)} sự kiện:\n" + '\n'.join(event_list)
                else:
                    original_output = f"Trong khoảng từ {start.strftime('%d/%m/%Y')} đến {end.strftime('%d/%m/%Y')} không có sự kiện nào!"
            else:
                original_output = "Vui lòng chỉ định ngày cụ thể để tra cứu âm lịch hoặc dương lịch!"
            _LOGGER.debug(f"Output for range: {original_output}")
            result = {
                'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')},
                'events': event_list,
                'is_lunar': is_lunar,
                'is_solar': is_solar or (not is_lunar and not is_event),
                'is_event': is_event,
                'output': await generate_humorous_output(hass, original_output, use_humor)
            }
        _LOGGER.debug(f"Final result: {result}")
        return result
    except Exception as e:
        _LOGGER.debug(f"Lỗi trong query_date: {str(e)}")
        return {"output": f"Lỗi xử lý: {str(e)}"}