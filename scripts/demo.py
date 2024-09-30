import json
from datetime import datetime, timezone
from typing_extensions import TypedDict
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, HumanMessage

class State(TypedDict):
    messages: list
    stop: bool
    can_activate: bool
    target_device: str

# 抽象化的設備資料
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

# Mock API 呼叫
def mock_api_call(device_id, path, method='GET'):
    mock_response = {
        "deviceID": device_id,
        "path": path,
        "state": "on" if device_id == "mock-device-456" else "off",
        "attributes": {"friendly_name": f"設備 {device_id}"},
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    return {"status": "success", "data": mock_response, "status_code": 200}

# 檢查設備狀態邏輯
def check_device_status(state: State):
    target_device = state['target_device']
    device_info = devices.get(target_device, {})
    related_devices = device_info.get('related_devices', '').split(';') if device_info else []

    try:
        statuses = []
        for related_device in related_devices:
            status_response = mock_api_call(related_device, devices[related_device]['path'])
            statuses.append(parse_device_status(state, status_response, related_device))

        state["can_activate"] = all(statuses)
        generate_final_message(state, target_device)
    except Exception as e:
        state["can_activate"] = False
        state["messages"].append(AIMessage(content=json.dumps({
            "status": False,
            "Message": f"檢查設備狀態時發生錯誤: {str(e)}"
        })))
    return state

# 解析設備狀態
def parse_device_status(state, status_response, device_name):
    device_state = status_response['data'].get('state', '').lower()
    last_updated = status_response['data'].get('last_updated')
    
    is_online = device_state in ['on', 'off']
    is_recent = (datetime.now(timezone.utc) - datetime.fromisoformat(last_updated)).total_seconds() < 300

    message = f"設備 '{device_name}' 狀態: {'開啟' if device_state == 'on' else '關閉'}, " \
              f"{'在線' if is_online else '離線'}, " \
              f"最後更新: {'最近' if is_recent else '不是最近'}"

    state["messages"].append(AIMessage(content=json.dumps({
        "status": is_online and is_recent,
        "Message": message
    })))
    return is_online and is_recent and device_state == 'on'

# 產生最終訊息
def generate_final_message(state, target_device):
    message = f"{'所有' if state['can_activate'] else '部分'}關聯設備已開啟並在線，{target_device}{'可以' if state['can_activate'] else '無法'}安全啟動"
    state["messages"].append(AIMessage(content=json.dumps({
        "status": state["can_activate"],
        "Message": message
    })))

# 啟動設備邏輯
def activate_device(state: State):
    target_device = state['target_device']
    if state["can_activate"]:
        try:
            mock_api_call(devices[target_device]['deviceID'], devices[target_device]['path'], method='POST')
            message = f"正在啟動 {target_device}"
            state["messages"].append(AIMessage(content=json.dumps({"status": True, "Message": message})))
        except Exception as e:
            state["messages"].append(AIMessage(content=json.dumps({
                "status": False,
                "Message": f"啟動 {target_device} 時發生錯誤: {str(e)}"
            })))
    else:
        state["messages"].append(AIMessage(content=json.dumps({
            "status": False,
            "Message": f"由於依賴的設備未開啟，{target_device} 未被啟動"
        })))
    state["stop"] = True
    return state

# LLM 交互
def chatbot(state: State):
    llm = ChatOpenAI(model="gpt-4")
    processed_messages = [AIMessage(content=json.loads(msg.content)["Message"]) if isinstance(msg, AIMessage) else msg for msg in state["messages"]]
    if not processed_messages:
        processed_messages = [HumanMessage(content=f"請檢查 {state['target_device']} 的關聯設備狀態")]
    
    response = llm.invoke(processed_messages)
    response_content = response.content if hasattr(response, 'content') else str(response)
    state["messages"].append(AIMessage(content=json.dumps({
        "status": "error" not in response_content.lower(),
        "Message": response_content
    })))
    return state

# 格式化回應
def format_line_response(result):
    summary = [json.loads(message.content)["Message"] for message in result["messages"]]
    final_status = "可以啟動" if result["can_activate"] else "無法啟動"
    return f"設備：{result['target_device']}\n狀態：{final_status}\n\n詳細信息：\n" + "\n".join(summary)

# 主程式
def main(target_device):
    graph_builder = StateGraph(State)
    graph_builder.add_node("check_status", check_device_status)
    graph_builder.add_node("activate_device", activate_device)
    graph_builder.add_node("chatbot", chatbot)
    graph_builder.add_edge(START, "check_status")
    graph_builder.add_edge("check_status", "chatbot")
    graph_builder.add_edge("chatbot", "activate_device")
    graph_builder.add_edge("activate_device", END)
    graph = graph_builder.compile()

    initial_state = {"messages": [], "stop": False, "can_activate": False, "target_device": target_device}
    result = graph.invoke(initial_state)
    return format_line_response(result)

if __name__ == "__main__":
    target_device = "開啟會議室冷氣"
    response = main(target_device)
    print("\nResponse：")
    print(response)