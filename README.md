
# 📅 Lịch Âm cho Home Assistant (Custom Component)

Tiện ích giúp tra cứu Âm Lịch và Sự Kiện theo ngày qua AI hoặc giao diện điều khiển trên Home Assistant.

---

## 🛠️ Cài đặt

### 1. Sao chép component

- Tải và giải nén dự án này.
- Copy thư mục `amlich` vào thư mục `custom_components` của Home Assistant.
- Copy file `amlich.ics` vào thư mục gốc của Home Assistant (ngang hàng với `configuration.yaml`).

### 2. Tạo biến trợ giúp

- Vào **Cài đặt → Thiết bị & Dịch vụ → Biến trợ giúp**.
- Tạo một **biến trợ giúp văn bản**, đặt tên là `tracuu`.
- Đảm bảo entity ID là: `input_text.tracuu`.

### 3. Khởi động lại Home Assistant

### 4. Cấu hình trong `configuration.yaml`

Thêm đoạn cấu hình sau:

```yaml
amlich:
  path: "/config/amlich.ics"
  api_key: "apikey"  # Thay "apikey" bằng API key Gemini của bạn

sensor:
  - platform: amlich  # Nếu đã có phần sensor, chỉ cần thêm dòng này bên dưới
```

### 5. Khởi động lại Home Assistant lần nữa

---

## ✅ Kiểm tra

- Sau khi khởi động lại, vào Developer Tools → States và kiểm tra xem đã có entity `sensor.tra_cuu_su_kien` chưa.
- Nếu chưa có, kiểm tra lại kỹ từ bước 2.

---

## ⚙️ Tạo tự động hóa (Automation)

### 6. Tự động hóa: Tra Cứu Âm Lịch Nâng Cao

```yaml
alias: Tự Động Tra Cứu Âm Lịch Nâng Cao
description: Tra Cứu Âm Lịch Nâng Cao
trigger:
  - platform: state
    entity_id: input_text.tracuu
  - platform: conversation
    command:
      - "{a} Âm lịch {date}"
      - "Âm lịch {date}"
      - "{a} am lich {date}"
      - "am lich {date}"
condition: []
action:
  - service: input_text.set_value
    target:
      entity_id: input_text.tracuu
    data:
      value: "\"{{ trigger.slots.date }}\""
  - variables:
      old_value: "{{ states('sensor.tra_cuu_su_kien') }}"
  - wait_template: "{{ states('sensor.tra_cuu_su_kien') != old_value }}"
    timeout: "00:00:05"
    continue_on_timeout: true
  - service: conversation.set_response
    data:
      response: >-
        {{ state_attr('sensor.tra_cuu_su_kien', 'output') |
        default(states('sensor.tra_cuu_su_kien'), true) }}
mode: single
```

---

### 7. Tự động hóa: Tra Cứu Sự Kiện Nâng Cao

```yaml
alias: Tự Động Tra Cứu Sự Kiện Nâng Cao
description: Tra Cứu Sự Kiện Nâng Cao
trigger:
  - platform: state
    entity_id: input_text.tracuu
  - platform: conversation
    command:
      - "{a} sự kiện {date}"
      - "sự kiện {date}"
      - "{a} su kien {date}"
      - "su kien {date}"
condition: []
action:
  - service: input_text.set_value
    target:
      entity_id: input_text.tracuu
    data:
      value: "\"{{ trigger.slots.date }}\""
  - variables:
      old_value: "{{ states('sensor.tra_cuu_su_kien') }}"
  - wait_template: "{{ states('sensor.tra_cuu_su_kien') != old_value }}"
    timeout: "00:00:05"
    continue_on_timeout: true
  - service: conversation.set_response
    data:
      response: >-
        {{ state_attr('sensor.tra_cuu_su_kien', 'output') |
        default(states('sensor.tra_cuu_su_kien'), true) }}
mode: single
```

---

## 🧪 Mẹo khắc phục

- Nếu kết quả phản hồi từ chatbot không đúng hoặc bị trễ, hãy thử **tăng timeout** từ `00:00:05` lên `00:00:10`.

```yaml
timeout: "00:00:10"
```

---

## 🤖 Tùy chỉnh phản hồi bằng AI

Để phản hồi sinh động hơn từ AI:

1. Mở file `amlich_core.py` trong thư mục `custom_components/amlich`.
2. Tìm dòng:

```python
async def query_date(hass: HomeAssistant, query, use_humor=False)
```

3. Thay `use_humor=False` thành `use_humor=True`.

> ⚠️ Lưu ý: Kết quả sẽ sinh động hơn nhưng phản hồi có thể **chậm hơn** do phụ thuộc tốc độ phản hồi của AI.

---

## 📩 Góp ý & Liên hệ

Bạn có thể tạo issue hoặc pull request nếu phát hiện lỗi hoặc muốn đóng góp cải tiến.

---

Chúc bạn sử dụng vui vẻ! ✨

---

## 🧑‍🏫 Hướng dẫn sử dụng

### 1. Tra cứu Âm Lịch

Để tra cứu âm lịch, trong câu chat cần **luôn có từ "âm lịch"**.

**Ví dụ:**

- "Âm lịch hôm nay"
- "Âm lịch ngày mai"
- "Cho tôi biết âm lịch 12/12/2025"

### 2. Tra cứu Sự Kiện

Để tra cứu sự kiện, trong câu chat cần **luôn có từ "sự kiện"**.

**Ví dụ:**

- "Sự kiện hôm nay"
- "Sự kiện ngày mai"
- "Cho tôi biết sự kiện 12/12/2025"
- "Sự kiện tuần này", "Sự kiện tuần sau"
- "Sự kiện tháng này", "Sự kiện tháng 1"

> Bạn có thể sử dụng **tiếng Việt không dấu** cho các câu lệnh, rất tiện lợi cho người dùng lười gõ dấu.
