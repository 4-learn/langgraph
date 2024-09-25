import json
import requests
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from langchain_core.messages import AIMessage, HumanMessage
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials

class State(TypedDict):
    messages: list
    stop: bool
    can_activate: bool
    target_device: str

def read_google_sheet():
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds = Credentials.from_service_account_file('secrets/t-planet.json', scopes=scopes)
    client = gspread.authorize(creds)
    sheet_url = "https://docs.google.com/spreadsheets/d/1uSp6WKTuEUufVm1nS8L-HWMsaeDEDyeanLPBm8J5TCY/edit?usp=sharing"
    sheet = client.open_by_url(sheet_url).get_worksheet(0)
    records = sheet.get_all_records()
    return {row['設備']: row for row in records}

devices = read_google_sheet()

def api_call(device_id, path, method='GET'):
    base_url = "https://e2live.duckdns.org:8155/api"
    headers = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI2Mjk0NmMzNjI2Nzc0YzJkOTkxZWFjYjk1NjkxZjgzZCIsImlhdCI6MTcxODc2Mzg5NywiZXhwIjoyMDM0MTIzODk3fQ.gq-oyg7bog6-1l8UW7QSiqTnQXzxrs0WbbE5qwIMaxI"
    }
    url = f"{base_url}/{path}/{device_id}"
    try:
        response = requests.request(method, url, headers=headers)
        response.raise_for_status()
        return {"status": "success", "data": response.json() if response.content else None, "status_code": response.status_code}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e), "status_code": getattr(e.response, 'status_code', None)}

def check_device_status(state: State):
    target_device = state['target_device']
    device_info = devices[target_device]
    related_devices = device_info['related_devices'].split(';') if device_info['related_devices'] else []

    try:
        statuses = []
        for related_device in related_devices:
            related_device_info = devices[related_device]
            status_response = api_call(related_device_info['deviceID'], related_device_info['path'])
            
            device_state = status_response.get('data', {}).get('state', '').lower()
            device_name = status_response.get('data', {}).get('attributes', {}).get('friendly_name', related_device)
            last_updated = status_response.get('data', {}).get('last_updated')

            is_online = device_state in ['on', 'off']
            is_recent = True
            if last_updated:
                last_updated_time = datetime.fromisoformat(last_updated)
                is_recent = (datetime.now(timezone.utc) - last_updated_time).total_seconds() < 300

            statuses.append(is_online and is_recent and device_state == 'on')
            state["messages"].append(AIMessage(content=json.dumps({
                "status": is_online and is_recent,
                "Message": f"設備 '{device_name}' 狀態: {'開啟' if device_state == 'on' else '關閉'}, " +
                           f"{'在線' if is_online else '離線'}, " +
                           f"最後更新: {'最近' if is_recent else '不是最近'}"
            })))

        state["can_activate"] = all(statuses)
        message = f"{'所有' if state['can_activate'] else '部分'}關聯設備已開啟並在線，{target_device}{'可以' if state['can_activate'] else '無法'}安全啟動"
        state["messages"].append(AIMessage(content=json.dumps({"status": state["can_activate"], "Message": message})))
    except Exception as e:
        state["can_activate"] = False
        state["messages"].append(AIMessage(content=json.dumps({
            "status": False,
            "Message": f"檢查設備狀態時發生錯誤: {str(e)}"
        })))
    return state

def activate_device(state: State):
    target_device = state['target_device']
    device_info = devices[target_device]
    if state["can_activate"]:
        try:
            api_call(device_info['deviceID'], device_info['path'], method='POST')
            message = f"正在啟動 {target_device}"
            status = True
        except Exception as e:
            message = f"啟動 {target_device} 時發生錯誤: {str(e)}"
            status = False
    else:
        message = f"由於依賴的設備未開啟，{target_device} 未被啟動"
        status = False
    
    state["messages"].append(AIMessage(content=json.dumps({"status": status, "Message": message})))
    state["stop"] = True
    return state

def chatbot(state: State):
    llm = ChatOpenAI(model="gpt-4")
    processed_messages = [AIMessage(content=json.loads(msg.content)["Message"]) if isinstance(msg, AIMessage) else msg for msg in state["messages"]]
    if not processed_messages:
        processed_messages = [HumanMessage(content=f"請檢查 {state['target_device']} 的關聯設備狀態")]
    
    response = llm.invoke(processed_messages)
    response_content = response.content if hasattr(response, 'content') else str(response)
    status = "error" not in response_content.lower() and "錯誤" not in response_content
    state["messages"].append(AIMessage(content=json.dumps({"status": status, "Message": response_content})))
    return state

def format_line_response(result):
    summary = []
    for message in result["messages"]:
        content = json.loads(message.content)
        if not content["status"]:
            summary.append(f"錯誤: {content['Message']}")
        elif "狀態:" in content["Message"]:
            summary.append(content["Message"])
        else:
            summary.append(f"分析: {content['Message'][:100]}...")

    final_status = "可以啟動" if result["can_activate"] else "無法啟動"
    response = f"設備：{result['target_device']}\n狀態：{final_status}\n\n"
    response += "詳細信息：\n" + "\n".join(summary)
    return response

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
    print("\nLINE Webhook 回應：")
    print(response)