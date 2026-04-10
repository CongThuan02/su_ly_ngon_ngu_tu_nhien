# NER API Documentation

## Base URL
```
https://xxxx-xxxx.ngrok-free.app
```
> URL thay đổi mỗi lần khởi động Colab. Lấy URL mới từ output của cell Bước 8.

---

## Endpoints

### 1. Kiểm tra server

**GET** `/`

**Response:**
```json
{
  "status": "NER API đang chạy"
}
```

---

### 2. Phân tích văn bản (NER)

**POST** `/predict`

**Headers:**
```
Content-Type: application/json
ngrok-skip-browser-warning: 1
```

**Request Body:**
```json
{
  "text": "20h học xử lý ngôn ngữ tự nhiên trên teams"
}
```

| Field | Type   | Mô tả                        |
|-------|--------|------------------------------|
| text  | string | Câu tiếng Việt cần phân tích |

---

**Response:**
```json
{
  "text": "20h học xử lý ngôn ngữ tự nhiên trên teams",
  "entities": [
    {
      "TIME": "20h",
      "TASK": "học xử lý ngôn ngữ tự nhiên",
      "LOCATION": "teams"
    }
  ]
}
```

| Field               | Type   | Mô tả                                  |
|---------------------|--------|----------------------------------------|
| text                | string | Câu văn bản đầu vào                    |
| entities            | array  | Mảng 1 phần tử chứa các nhãn tìm được |
| entities[].TIME     | string | Thời gian (nếu có)                     |
| entities[].TASK     | string | Công việc (nếu có)                     |
| entities[].LOCATION | string | Địa điểm (nếu có)                      |
| entities[].PARTNER  | string | Đối tác (nếu có)                       |

---

## Nhãn (Labels)

| Nhãn     | Ý nghĩa        | Ví dụ                              |
|----------|----------------|------------------------------------|
| TIME     | Thời gian      | `20h`, `sáng mai lúc 9h`, `thứ 4` |
| TASK     | Công việc      | `họp dự án`, `học lập trình`       |
| LOCATION | Địa điểm       | `phòng họp tầng 3`, `teams`, `zoom`|
| PARTNER  | Đối tác        | `công ty FPT`, `viettel`           |

---

## Flutter Code mẫu

### pubspec.yaml
```yaml
dependencies:
  http: ^1.0.0
```

### ner_service.dart
```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

class NERService {
  static const String baseUrl = "https://xxxx-xxxx.ngrok-free.app";

  static Future<Map<String, dynamic>> predict(String text) async {
    final response = await http.post(
      Uri.parse('$baseUrl/predict'),
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': '1',
      },
      body: jsonEncode({'text': text}),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception('Lỗi API: ${response.statusCode}');
    }
  }
}
```

### Cách dùng trong Flutter
```dart
final result = await NERService.predict("20h họp dự án tại phòng A với viettel");

print(result['text']);       // "20h họp dự án tại phòng A với viettel"

final entities = result['entities'][0];  // lấy phần tử đầu tiên
print(entities['TIME']);     // "20h"
print(entities['TASK']);     // "họp dự án"
print(entities['LOCATION']); // "phòng A"
print(entities['PARTNER']);  // "viettel"
```

---

## Lưu ý

- API chỉ hoạt động khi **Colab đang chạy** cell Bước 8.
- URL ngrok **thay đổi** mỗi lần restart Colab — cần cập nhật lại `baseUrl` trong Flutter.
- Hỗ trợ cả văn bản **có dấu** và **không dấu** tiếng Việt.
