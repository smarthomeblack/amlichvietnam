import re
import json
import requests
from datetime import datetime, timedelta
from dateutil.parser import parse
from icalendar import Calendar
import logging
import os
from homeassistant.core import HomeAssistant

# Thiết lập logging
_LOGGER = logging.getLogger(__name__)

# Cấu hình Gemini AI
GEMINI_API_KEY = None
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def set_api_key(api_key):
    global GEMINI_API_KEY
    GEMINI_API_KEY = api_key
    _LOGGER.debug(f"Đã đặt Gemini API key: {'***' if api_key else 'None'}")

# Lưu trữ dữ liệu ICS toàn cục
_lunar_dates = {}
_events = {}

# Đọc file ICS và lưu dữ liệu
def load_ics_file(file_path):
    global _lunar_dates, _events
    _lunar_dates = {}
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
                if isinstance(start_date, datetime):
                    start_date = start_date.date()
                if re.match(r'^\d{1,2}/\d{1,2}(?:\s*\(N\))?$', summary):
                    lunar_date = summary.replace('(N)', '').strip()
                    _lunar_dates[start_date] = lunar_date
                else:
                    if start_date not in _events:
                        _events[start_date] = []
                    _events[start_date].append(summary)
            _LOGGER.info(f"Đã tải {len(_lunar_dates)} ngày âm lịch và {sum(len(e) for e in _events.values())} sự kiện")
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

# Hàm sửa lỗi chính tả bằng Gemini AI
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
- Ví dụ:
  - 'tuaann nay' → 'tuần này'
  - '12 táng 12' → '12 tháng 12'
  - 'ngàyy này tuầnn sau' → 'ngày này tuần sau'
  - 'sự kiện tuaann nay' → 'sự kiện tuần này'
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

# Hàm gọi Gemini API để phân tích input
async def parse_with_gemini(hass: HomeAssistant, input_text):
    if not GEMINI_API_KEY:
        _LOGGER.error("Không có Gemini API key được cấu hình")
        return {'error': 'Không có Gemini API key'}
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    is_event = input_text.lower().startswith('sự kiện')
    current_date = datetime.now().date()
    current_year = current_date.year
    prompt = f"""Hôm nay là {current_date.strftime('%Y-%m-%d')}. Hãy phân tích input sau và trả về JSON theo định dạng:
- Nếu là ngày cụ thể: {{"date": "YYYY-MM-DD", "is_event": {"true" if is_event else "false"}}}
- Nếu là khoảng thời gian (như tuần/tháng): {{"range": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}, "is_event": {"true" if is_event else "false"}}}
- Nếu không xác định được ngày, trả về: {{"error": "Không thể xác định ngày"}}.
- Không trả về date hoặc range là null. Luôn trả về JSON hợp lệ với 'date', 'range', hoặc 'error'.

Hướng dẫn:
1. Các tháng bằng chữ tiếng Việt: 'sáu' là tháng 6, 'bảy' là tháng 7, v.v.
2. Các cụm thời gian:
   - 'ngày này tuần sau', 'hôm nay tuần sau': ngày hiện tại cộng 7 ngày.
   - 'ngày này tháng sau': ngày hiện tại trong tháng sau (giữ nguyên ngày, thay tháng).
   - 'thứ 3 tuần sau': ngày thứ Ba của tuần sau (tính từ thứ Hai tuần sau, tức ngày hiện tại cộng 7 ngày rồi điều chỉnh đến thứ Ba).
   - 'tuần này': khoảng thời gian từ thứ Hai đến Chủ Nhật của tuần hiện tại.
   - 'tháng sáu': khoảng thời gian từ ngày 1 đến ngày cuối của tháng 6 trong năm hiện tại ({current_year}).
   - 'tháng này': khoảng thời gian từ ngày 1 đến ngày cuối của tháng hiện tại.
3. Nếu input có tiền tố 'sự kiện', đặt is_event=true và xử lý phần còn lại.
4. Nếu không có năm, sử dụng năm hiện tại ({current_year}).
5. Luôn trả về JSON hợp lệ, không chỉ trả về 'is_event'.

Ví dụ:
- Input: 'ngày này tuần sau' → {{"date": "2025-05-19", "is_event": false}}
- Input: 'thứ 3 tuần sau' → {{"date": "2025-05-20", "is_event": false}}
- Input: 'sự kiện tháng sáu' → {{"range": {{"start": "2025-06-01", "end": "2025-06-30"}}, "is_event": true}}
- Input: '12 tháng 12' → {{"date": "2025-12-12", "is_event": false}}
- Input: 'sự kiện tuần này' → {{"range": {{"start": "2025-05-12", "end": "2025-05-18"}}, "is_event": true}}
- Input: 'sự kiện tháng này' → {{"range": {{"start": "2025-05-01", "end": "2025-05-31"}}, "is_event": true}}
- Input: 'sự kiện 12/12/2025' → {{"date": "2025-12-12", "is_event": true}}

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
                    result['is_event'] = result.get('is_event', is_event)
                    if 'date' not in result and 'range' not in result and 'error' not in result:
                        _LOGGER.debug("Response từ Gemini thiếu date, range hoặc error")
                        return {'error': 'Response từ Gemini không hợp lệ'}
                    return result
                else:
                    _LOGGER.debug("Không tìm thấy 'candidates' trong response từ Gemini AI")
                    return {'error': 'Response từ Gemini AI không hợp lệ'}
            else:
                _LOGGER.debug(f"Lỗi Gemini API: {response.status_code} - {response.text}")
                return {'error': f'Lỗi khi gọi Gemini API: {response.status_code} - {response.text}'}
        except Exception as e:
            _LOGGER.debug(f"Lỗi khi gọi Gemini API: {str(e)}")
            return {'error': f'Lỗi kết nối Gemini API: {str(e)}'}

    return await hass.async_add_executor_job(make_request)

# Hàm chuyển đổi input thành ngày hoặc khoảng thời gian
async def parse_input(hass: HomeAssistant, input_text, is_fixed=False):
    input_text = input_text.lower().strip()
    today = datetime.now().date()
    _LOGGER.debug(f"Ngày hiện tại là {today}")

    is_event = input_text.startswith('sự kiện')
    if is_event:
        date_part = input_text.replace('sự kiện', '', 1).strip()
    else:
        date_part = input_text

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
        date = exact_matches[date_part]
        _LOGGER.debug(f"Ngày parsed (exact match) - Ngày: {date}")
        return {'date': date.strftime('%Y-%m-%d'), 'is_event': is_event}

    if date_part == 'ngày này tháng sau':
        date = (today + timedelta(days=31)).replace(day=today.day)
        _LOGGER.debug(f"Ngày parsed (tháng sau) - Ngày: {date}")
        return {'date': date.strftime('%Y-%m-%d'), 'is_event': is_event}

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
            _LOGGER.debug(f"Ngày parsed - Ngày: {day}, Tháng: {month}, Năm: {year}")
            try:
                date = datetime(year, month, day).date()
                return {'date': date.strftime('%Y-%m-%d'), 'is_event': is_event}
            except ValueError:
                pass

    text_pattern = r'^(?:ngày\s+)?(\d{1,2})\s+tháng\s+(\d{1,2})(?:\s+năm\s+(\d{2,4}))?$'
    match = re.match(text_pattern, date_part)
    if match:
        day, month = map(int, match.groups()[:2])
        year = int(match.groups()[2]) if match.groups()[2] else today.year
        if len(str(year)) == 2:
            year = 2000 + year
        _LOGGER.debug(f"Ngày parsed (text) - Ngày: {day}, Tháng: {month}, Năm: {year}")
        try:
            date = datetime(year, month, day).date()
            return {'date': date.strftime('%Y-%m-%d'), 'is_event': is_event}
        except ValueError:
            pass

    month_names = {
        'một': 1, 'hai': 2, 'ba': 3, 'bốn': 4, 'năm': 5, 'sáu': 6,
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
                _LOGGER.debug(f"Tháng parsed - Tháng: {month}, Từ: {month_name}")
                return {'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')}, 'is_event': is_event}

    month_num_pattern = r'^tháng\s+(\d{1,2})$'
    match = re.match(month_num_pattern, date_part)
    if match:
        month = int(match.group(1))
        if 1 <= month <= 12:
            start = today.replace(month=month, day=1)
            end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
            _LOGGER.debug(f"Tháng parsed - Tháng: {month}")
            return {'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')}, 'is_event': is_event}

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
            _LOGGER.debug(f"Khoảng thời gian parsed - Từ: {start}, Đến: {end}")
            return {'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')}, 'is_event': is_event}

    if not is_fixed:
        _LOGGER.debug(f"Input không khớp, thử sửa lỗi chính tả: {input_text}")
        fixed_input = await fix_spelling(hass, input_text)
        if fixed_input.lower() != input_text:
            _LOGGER.debug(f"Thử lại parse_input với input sửa: {fixed_input}")
            return await parse_input(hass, fixed_input, is_fixed=True)
    
    _LOGGER.debug(f"Chuyển sang Gemini AI cho input: {input_text}")
    return await parse_with_gemini(hass, input_text)

# Hàm gọi Gemini API để tạo output hài hước
async def generate_humorous_output(hass: HomeAssistant, original_output, use_humor=False):
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
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                _LOGGER.error(f"Lỗi Gemini API (hài hước): {response.status_code} - {response.text}")
                return original_output
        except Exception as e:
            _LOGGER.error(f"Lỗi tạo output hài hước: {str(e)}")
            return original_output

    return await hass.async_add_executor_job(make_request)

# Hàm tra cứu và tạo kết quả
async def query_date(hass: HomeAssistant, query, use_humor=False):
    global _lunar_dates, _events
    try:
        parsed = await parse_input(hass, query)
        if not parsed or 'error' in parsed:
            original_output = parsed.get('error', "Không thể phân tích input. Vui lòng thử lại!")
            return {"output": await generate_humorous_output(hass, original_output, use_humor)}

        result = {}
        is_event = parsed.get('is_event', False)
        if 'date' in parsed and parsed['date']:
            try:
                date = datetime.strptime(parsed['date'], '%Y-%m-%d').date()
                weekday = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật'][date.weekday()]
                lunar_date = _lunar_dates.get(date, 'Không có dữ liệu')
                if is_event:
                    event_list = _events.get(date, [])
                    if event_list:
                        events_str = ', '.join(event_list)
                        original_output = f"Dương Lịch Ngày {date.strftime('%d/%m/%Y')} ({weekday}) có sự kiện là {events_str} (ngày {lunar_date} Âm Lịch)!"
                    else:
                        original_output = f"Dương Lịch Ngày {date.strftime('%d/%m/%Y')} ({weekday}) không có sự kiện nào!"
                else:
                    original_output = f"Dương Lịch Ngày {date.strftime('%d/%m/%Y')} ({weekday}) là ngày {lunar_date} Âm Lịch"
                result = {
                    'date': date.strftime('%Y-%m-%d'),
                    'lunar_date': lunar_date,
                    'events': _events.get(date, []),
                    'output': await generate_humorous_output(hass, original_output, use_humor)
                }
            except (ValueError, TypeError) as e:
                _LOGGER.debug(f"Lỗi khi xử lý ngày: {str(e)}")
                original_output = "Ngày không hợp lệ. Vui lòng kiểm tra lại!"
                return {"output": await generate_humorous_output(hass, original_output, use_humor)}
        elif 'range' in parsed:
            start = datetime.strptime(parsed['range']['start'], '%Y-%m-%d').date()
            end = datetime.strptime(parsed['range']['end'], '%Y-%m-%d').date()
            event_list = []
            for d in (start + timedelta(n) for n in range((end - start).days + 1)):
                if d in _events:
                    for evt in _events[d]:
                        lunar_date = _lunar_dates.get(d, 'Không có dữ liệu')
                        event_list.append(f"Ngày {d.strftime('%d/%m/%Y')} ({lunar_date} Âm Lịch) là {evt}")
            if is_event:
                if event_list:
                    original_output = f"Trong khoảng từ {start.strftime('%d/%m/%Y')} đến {end.strftime('%d/%m/%Y')} có {len(event_list)} sự kiện:\n" + '\n'.join(event_list)
                else:
                    original_output = f"Trong khoảng từ {start.strftime('%d/%m/%Y')} đến {end.strftime('%d/%m/%Y')} không có sự kiện nào!"
            else:
                original_output = "Vui lòng chỉ định ngày cụ thể để tra cứu âm lịch!"
            result = {
                'range': {'start': start.strftime('%Y-%m-%d'), 'end': end.strftime('%Y-%m-%d')},
                'events': event_list,
                'output': await generate_humorous_output(hass, original_output, use_humor)
            }
        return result
    except Exception as e:
        _LOGGER.debug(f"Lỗi trong query_date: {str(e)}")
        return {"output": f"Lỗi xử lý: {str(e)}"}