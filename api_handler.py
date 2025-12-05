import requests
import json
import os
from urllib.parse import quote
from bs4 import BeautifulSoup
import datetime
import random

# --- 配置 ---
COOKIE_FILE = 'cookies.json'
BASE_HEADERS = {
    'Host': 'yyticket.jinanaoti.com',
    'Proxy-Connection': 'keep-alive',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541211) XWEB/16815 Flue',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

def load_cookies_from_file():
    """从 JSON 文件加载 Cookies 到字典中"""
    if not os.path.exists(COOKIE_FILE):
        return {}
    try:
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"加载 Cookie 失败: {e}")
        return {}

def save_cookies_to_file(session_cookies):
    """
    将 Session 中的 Cookies 更新到 JSON 文件中。
    Requests 的 session 会自动合并新旧 Cookie，我们只需保存最终状态。
    """
    try:
        # 获取当前的 Cookie 字典
        current_cookies = requests.utils.dict_from_cookiejar(session_cookies)
        
        # 为了防止覆盖掉文件中存在但 session 中没有的旧 cookie（虽然 session 通常会包含所有），
        # 我们先读取文件，更新后再写入。
        saved_cookies = load_cookies_from_file()
        saved_cookies.update(current_cookies)
        
        with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
            json.dump(saved_cookies, f, indent=4, ensure_ascii=False)
            
    except Exception as e:
        print(f"保存 Cookie 失败: {e}")

def _make_request(url, referer):
    """
    内部通用请求函数，处理 Cookie 的加载和保存
    """
    # 1. 创建 Session 对象 (它会自动处理 Cookie)
    session = requests.Session()
    
    # 2. 设置 Header
    headers = BASE_HEADERS.copy()
    headers['Referer'] = referer
    session.headers.update(headers)
    
    # 3. 加载并设置 Cookies
    cookies_dict = load_cookies_from_file()
    session.cookies.update(cookies_dict)
    
    try:
        # 4. 发送请求
        response = session.get(url, timeout=10)
        
        # 5. 请求成功后，立即保存/更新 Cookies 到文件
        # session.cookies 中现在包含了发送时的 cookie 和服务器返回的新 cookie
        save_cookies_to_file(session.cookies)
        
        return True, response.json()
        
    except Exception as e:
        return False, str(e)

def _make_request(url, referer, is_json=True):
    """
    内部通用请求函数，处理 Cookie 的加载和保存
    新增 is_json 参数，用于区分返回 HTML 还是 JSON
    """
    session = requests.Session()
    # 设置 Header
    headers = BASE_HEADERS.copy()
    headers['Referer'] = referer
    
    # 根据请求类型合并特定的 Header
    if referer.endswith("GetDayPlay"):
        headers.update(BASE_HEADERS)
    # else if referer.endswith("CD/Index2"):
    #     headers.update(DASHBOARD_HEADERS) 
    
    session.headers.update(headers)
    session.cookies.update(load_cookies_from_file())
    
    try:
        response = session.get(url, timeout=10)
        
        # 保存可能更新的 Cookies
        save_cookies_to_file(session.cookies)
        
        if is_json:
            return True, response.json()
        else:
            response.encoding = 'utf-8'
            return True, response.text
        
    except Exception as e:
        return False, str(e)

# --- 外部调用的接口方法 ---

def send_sms_code(phone):
    """发送验证码接口"""
    url = f"http://yyticket.jinanaoti.com/JNMY/SendSMSVerifyCode?Phone={phone}"
    referer = "http://yyticket.jinanaoti.com/JNMY/Login"
    
    success, result = _make_request(url, referer)
    
    if not success:
        return False, f"网络请求异常: {result}"
        
    # 业务逻辑判断
    if result.get("Code") == 1:
        # 再次确认返回的手机号
        if result.get("Data", {}).get("Phone") == phone:
            return True, "发送成功"
        else:
            return False, "服务器返回手机号不匹配"
    else:
        return False, result.get("Msg", "未知错误")

def check_login(phone, code):
    """登录校验接口"""
    url = f"http://yyticket.jinanaoti.com/JNMY/CheckPhoneCode?phone={phone}&code={code}"
    referer = "http://yyticket.jinanaoti.com/jnmy/login"
    
    success, result = _make_request(url, referer)
    
    if not success:
        return False, f"网络请求异常: {result}"

    # 业务逻辑判断
    if result.get("Code") == 1:
        return True, result.get("Msg", "登录成功")
    else:
        return False, result.get("Msg", "验证失败")
    

    # 针对主页请求的特定 Headers (参考你的抓包)
DASHBOARD_HEADERS = {
    'Host': 'yyticket.jinanaoti.com',
    'Proxy-Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/wxpic,image/webp,image/apng,*/*;q=0.8',
    'Referer': 'http://yyticket.jinanaoti.com/cd/home',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

def get_dashboard_html():
    """
    获取主页 HTML 内容 (修改为调用 _make_request)
    """
    url = "http://yyticket.jinanaoti.com/CD/Index2"
    referer = "http://yyticket.jinanaoti.com/cd/home"
    
    return _make_request(url, referer, is_json=False)

def fetch_image_bytes(image_url):
    """
    下载图片并返回字节流
    """
    if not image_url.startswith('http'):
        image_url = 'http://yyticket.jinanaoti.com' + image_url
        
    session = requests.Session()
    # 图片请求通常不需要复杂的 Header，但带上 User-Agent 比较保险
    session.headers.update({'User-Agent': DASHBOARD_HEADERS['User-Agent']})
    
    try:
        resp = session.get(image_url, timeout=10)
        if resp.status_code == 200:
            return resp.content
        return None
    except:
        return None
    

# 获取预订页面的配置信息 (日期和场地) 
def get_booking_options(item_type):
    """
    访问 particulars 页面，解析可用的日期和场地名称
    """
    url = f"http://yyticket.jinanaoti.com/cd/particulars?type={item_type}"
    # Referer 通常是列表页
    referer = "http://yyticket.jinanaoti.com/CD/Index2"
    
    success, content = _make_request(url, referer, is_json=False)
    
    if not success:
        return False, f"请求页面失败: {content}"
    
    try:
        soup = BeautifulSoup(content, 'html.parser')
        
        # 1. 解析日期 (class="dataCont")
        dates = []
        date_cont = soup.find('div', class_='dataCont')
        if date_cont:
            for span in date_cont.find_all('span'):
                day = span.get('data-day')
                if day:
                    dates.append(day)
                    
        # 2. 解析场地名称 (class="dataCont123")
        areas = []
        area_cont = soup.find('div', class_='dataCont123')
        if area_cont:
            for span in area_cont.find_all('span'):
                # 获取 data-day 属性作为场地名称 (例如: 羽毛球北训场)
                area_name = span.get('data-day')
                if area_name:
                    areas.append(area_name)
        
        if not dates:
            return False, "未找到可用日期信息"
        if not areas:
            # 某些项目可能没有 dataCont123 (比如不需要选场地的)，做个兼容
            # 但根据你的描述，这里必须要有
            return False, "未找到场地名称信息"

        return True, {
            "dates": dates,       # 所有日期列表
            "areas": areas,       # 所有场地列表
            "default_date": dates[0], # 默认第一个
            "default_area": areas[0]  # 默认第一个
        }

    except Exception as e:
        return False, f"解析页面出错: {e}"


def get_venue_data(item_type, evaluate_name, day):
    """
    获取某一运动项目在特定日期的场地数据
    :param item_type: 运动项目类型，如 '0004'
    :param evaluate_name: 场地名称，如 '羽毛球北讯场' (中文需要编码)
    :param day: 日期，如 '2025-11-21'
    :return: 成功状态 (bool) 和 结果 (dict/str)
    """
    # 编码中文参数
    encoded_evaluate = quote(evaluate_name)
    
    # 构造请求 URL
    url = f"http://yyticket.jinanaoti.com/cd/GetDayPlay?type={item_type}&Evaluate={encoded_evaluate}&Day={day}"
    # 构造 Referer (根据抓包，Referer 应该是 particulars 页面)
    referer = f"http://yyticket.jinanaoti.com/cd/particulars?type={item_type}"
    
    success, result = _make_request(url, referer, is_json=True)
    
    if not success:
        return False, f"网络请求异常: {result}"
        
    # 假设 Code=1 表示成功
    if result.get("Code") == 1:
        data = result.get("Data")
        # 如果 Data 为空 或者 长度为0，视为无数据
        if not data:
            return True, generate_mock_venue_data(item_type, evaluate_name, day)
        return True, data
    else:
        return False, result.get("Msg", "未知错误")
    
def get_next_7_days():
    """获取今天开始的未来7天日期列表"""
    dates = []
    today = datetime.date.today()
    for i in range(7):
        d = today + datetime.timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates    

def generate_mock_venue_data(item_type, area_name, date):
    """
    当接口无数据时，生成模拟数据供测试 UI
    """
    print(f"警告：接口未返回数据，正在生成 {date} 的模拟数据...")
    
    mock_data = []
    # 模拟 10 个场地
    for i in range(1, 11):
        court_name = f"{area_name} {i}号场(模拟)"
        rtnlist = []
        # 模拟 07:00 - 21:00
        for hour in range(7, 22):
            time_str = f"{hour:02d}:00"
            
            # 随机生成一些状态
            status_rand = random.random()
            c7 = "可预约"
            c8 = "0" # 0未订, 1已订
            desc = None
            
            if status_rand > 0.8:
                c8 = "1" # 已占用
            elif status_rand > 0.9:
                c7 = "不可预约"
            
            rtnlist.append({
                "TicketLevelName": time_str,
                "MemberPrice": 40.0 if hour < 17 else 50.0,
                "TicketTypeNo": f"mock_type_{i}",
                "TicketLevelNo": f"mock_level_{hour}",
                "CDefault7": c7,
                "CDefault8": c8,
                "Description": desc
            })
            
        mock_data.append({
            "name": court_name,
            "rtnlist": rtnlist
        })
        
    return mock_data