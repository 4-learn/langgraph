import json
from datetime import datetime, timezone
from langchain.tools import tool

# 模擬設備資料
def load_mock_device_data():
    return {
        "開啟會議室冷氣": {
            "deviceID": "mock-device-123",
            "path": "control/ac",
            "related_devices": "mock-device-456;mock-device-789"
        },
        "mock-device-456": {
            "deviceID": "mock-device-456",
            "path": "control/fan",
            "related_devices": ""
        },
        "mock-device-789": {
            "deviceID": "mock-device-789",
            "path": "control/lights",
            "related_devices": ""
        }
    }

devices = load_mock_device_data()

# 模擬 API 呼叫
def mock_api_call(device_id, path, method='GET'):
    mock_response = {
        "deviceID": device_id,
        "path": path,
        "state": "on" if device_id == "mock-device-456" else "off",
        "attributes": {"friendly_name": f"設備 {device_id}"},
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    return {"status": "success", "data": mock_response, "status_code": 200}

@tool
def manage_device(target_device: str) -> str:
    """管理指定的設備，檢查設備狀態，分析是否可以啟動，並嘗試啟動設備。

    Args:
        target_device (str): 要管理的設備名稱，例如 "開啟會議室除濕機" 或 "關閉會議室冷氣"

    Returns:
        str: 包含設備狀態、分析結果和操作結果的詳細報告
    """
    print(f"原始輸入: {target_device}")

    # 嘗試解析可能的 JSON 輸入
    try:
        input_data = json.loads(target_device)
        if isinstance(input_data, dict) and 'message' in input_data:
            target_device = input_data['message']
    except json.JSONDecodeError:
        pass  # 如果不是 JSON，就使用原始輸入

    target_device = target_device.strip()

    # 直接匹配完整的設備名稱
    if target_device in devices:
        print(f"精確匹配到設備: {target_device}")
    else:
        # 部分匹配
        possible_devices = [device for device in devices.keys() if device.lower() in target_device.lower()]
        if possible_devices:
            target_device = max(possible_devices, key=len)  # 選擇最長的匹配
            print(f"部分匹配到設備: {target_device}")
        else:
            return f"錯誤：找不到設備 '{target_device}'。可用的設備包括: {', '.join(devices.keys())}"

    device_info = devices[target_device]
    related_devices = device_info['related_devices'].split(';') if device_info['related_devices'] else []

    # 檢查設備狀態
    all_devices_ok = True
    messages = []
    for related_device_id in related_devices:
        print(f"檢查相關設備: {related_device_id}")
        status_response = mock_api_call(related_device_id, 'states')
        print(f"相關設備 '{related_device_id}' 的狀態回應: {status_response}")

        if status_response['status'] == 'success':
            device_data = status_response.get('data', {})
            device_state = device_data.get('state', '').lower()
            device_name = device_data.get('attributes', {}).get('friendly_name', related_device_id)
            last_updated = device_data.get('last_updated')

            is_online = device_state in ['on', 'off']
            is_recent = True
            if last_updated:
                last_updated_time = datetime.fromisoformat(last_updated)
                is_recent = (datetime.now(timezone.utc) - last_updated_time).total_seconds() < 300

            device_ok = is_online and is_recent
            if not device_ok:
                all_devices_ok = False

            status_msg = f"設備 '{device_name}' (ID: {related_device_id}) 狀態: {'開啟' if device_state == 'on' else '關閉'}, " \
                         f"{'在線' if is_online else '離線'}, " \
                         f"最後更新: {'最近' if is_recent else '不是最近'}"
            messages.append(status_msg)
            print(status_msg)
        else:
            error_msg = f"錯誤: 無法獲取設備 '{related_device_id}' 的狀態: {status_response.get('message', '未知錯誤')}"
            messages.append(error_msg)
            print(error_msg)
            all_devices_ok = False

    can_activate = all_devices_ok
    status_summary = f"{'所有' if can_activate else '部分'}關聯設備狀態正常，{target_device}{'可以' if can_activate else '無法'}安全執行"
    messages.append(status_summary)
    print(status_summary)

    # 執行設備操作
    if can_activate:
        try:
            operation_response = mock_api_call(device_info['deviceID'], device_info['path'], method='POST')
            print(f"設備操作的 API 回應: {operation_response}")
            if operation_response['status'] == 'success':
                operation_message = f"成功執行操作: {target_device}"
            else:
                operation_message = f"執行操作 {target_device} 時發生錯誤: {operation_response.get('message', '未知錯誤')}"
        except Exception as e:
            operation_message = f"執行操作 {target_device} 時發生異常: {str(e)}"
    else:
        operation_message = f"由於部分相關設備狀態異常，未執行 {target_device} 的操作"

    messages.append(operation_message)
    print(operation_message)

    # 格式化回應
    response = f"設備：{target_device}\n狀態：{'可以執行' if can_activate else '無法執行'}\n\n"
    response += "詳細信息：\n" + "\n".join(messages)

    return response
