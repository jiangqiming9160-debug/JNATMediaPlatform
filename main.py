import json
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk # 需安装 pillow
from bs4 import BeautifulSoup  # 需安装 beautifulsoup4
import io
import re
import threading
import api_handler
from urllib.parse import urlparse, parse_qs


# --- 全局变量 ---
# 用于防止图片被垃圾回收
image_references = [] 

# --- 业务逻辑：发送验证码 (保持不变) ---
def start_countdown(remaining=60):
    if remaining > 0:
        send_button.config(text=f"{remaining}s 后重发", state=tk.DISABLED)
        root.after(1000, start_countdown, remaining - 1)
    else:
        send_button.config(text="发送验证码", state=tk.NORMAL)

def handle_send_code():
    phone = phone_entry.get()
    if not re.fullmatch(r'1\d{10}', phone):
        messagebox.showwarning("输入错误", "请输入有效的11位手机号码。")
        return
    send_button.config(state=tk.DISABLED, text="发送中...")
    threading.Thread(target=thread_send_task, args=(phone,)).start()

def thread_send_task(phone):
    success, msg = api_handler.send_sms_code(phone)
    if success:
        messagebox.showinfo("发送结果", f"验证码已发送至 {phone}")
        root.after(0, start_countdown)
    else:
        messagebox.showerror("发送失败", msg)
        root.after(0, lambda: send_button.config(text="发送验证码", state=tk.NORMAL))

# --- 业务逻辑：登录与新窗口 ---

def handle_login():
    phone = phone_entry.get()
    code = code_entry.get()
    
    if not re.fullmatch(r'1\d{10}', phone):
        messagebox.showwarning("输入错误", "请检查手机号格式。")
        return
    if not code:
        messagebox.showwarning("输入错误", "请输入验证码。")
        return
    
    login_button.config(text="登录中...", state=tk.DISABLED)
    threading.Thread(target=thread_login_task, args=(phone, code)).start()

def thread_login_task(phone, code):
    success, msg = api_handler.check_login(phone, code)
    
    # 恢复登录按钮状态
    root.after(0, lambda: login_button.config(text="登 录", state=tk.NORMAL))

    if success:
        # 登录成功，隐藏主窗口，打开新窗口
        root.after(0, lambda: [root.withdraw(), open_dashboard_window()])
    else:
        root.after(0, lambda: messagebox.showerror("登录失败", msg))

# --- 新窗口逻辑：显示数据 ---

def open_dashboard_window():
    """打开大的数据显示窗口"""
    dashboard = tk.Toplevel()
    dashboard.title("场馆服务列表")
    dashboard.geometry("600x500")
    
    # 当新窗口关闭时，结束整个程序（或者你可以选择 root.deiconify() 显示回登录窗口）
    dashboard.protocol("WM_DELETE_WINDOW", root.destroy)
    
    loading_label = tk.Label(dashboard, text="正在加载数据...", font=("Arial", 14))
    loading_label.pack(pady=50)
    
    # 启动线程加载数据，避免界面卡死
    threading.Thread(target=thread_load_dashboard_data, args=(dashboard, loading_label)).start()

def thread_load_dashboard_data(window, loading_label):
    """后台加载 HTML 并解析，下载图片"""
    success, html_content = api_handler.get_dashboard_html()
    
    if not success:
        window.after(0, lambda: loading_label.config(text=f"加载失败: {html_content}"))
        return

    # 解析 HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    menu_cont = soup.find('div', class_='menuCont')
    
    items_data = []
    
    if menu_cont:
        links = menu_cont.find_all('a')
        for link in links:
            # 提取名称
            p_tag = link.find('p')
            name = p_tag.text.strip() if p_tag else "未知项目"
            
            # 提取图片 URL
            img_tag = link.find('img')
            img_url = img_tag.get('src') if img_tag else None
            
            # 下载图片数据
            img_bytes = None
            if img_url:
                img_bytes = api_handler.fetch_image_bytes(img_url)
            
            items_data.append({
                "name": name,
                "img_bytes": img_bytes
            })
    else:
         window.after(0, lambda: loading_label.config(text="未找到菜单内容，请检查 Cookie 是否有效。"))
         return

    # 数据准备好后，回到主线程渲染 UI
    window.after(0, lambda: render_dashboard_ui(window, loading_label, items_data))

def render_dashboard_ui(window, loading_label, items_data):
    loading_label.destroy()
    container = tk.Frame(window)
    container.pack(expand=True, fill='both', padx=20, pady=20)

    columns = 3 
    
    for i, item in enumerate(items_data):
        row = i // columns
        col = i % columns
        
        # 绑定点击事件
        click_command = lambda i=item["item_info"]: show_venue_page(i, window)
        
        # --- 修改开始：使用原生 compound 属性 ---
        
        # 创建按钮，默认先设置文字和点击事件
        # relief="raised" 是标准按钮样式
        card = tk.Button(container, 
                         text=item["name"], 
                         command=click_command,
                         font=("微软雅黑", 10),
                         bg="#f0f0f0",
                         bd=2,
                         relief="raised",
                         width=20,    # 限制宽度，防止文字过长撑乱布局
                         height=6)    # 限制高度 (注意：如果有图片，单位是像素；无图片是字符数，Tkinter特性)

        # 处理图片
        if item["img_bytes"]:
            try:
                pil_image = Image.open(io.BytesIO(item["img_bytes"]))
                pil_image = pil_image.resize((50, 50), Image.Resampling.LANCZOS) #稍微缩小一点图片适应按钮
                tk_image = ImageTk.PhotoImage(pil_image)
                image_references.append(tk_image) # 防止回收
                
                # 关键设置：compound="top" 让图片位于文字上方
                # 设置了 image 后，height/width 的单位会自动变为像素，所以这里需要重新调整一下尺寸感
                card.config(image=tk_image, compound="top", height=100, width=150) 
            except Exception as e:
                card.config(text=f"[图裂]\n{item['name']}")
        
        # 布局
        card.grid(row=row, column=col, padx=10, pady=10)
        
        # --- 修改结束 ---

    for x in range(columns):
        container.grid_columnconfigure(x, weight=1)


# 用于在项目卡片被点击时使用
class ItemInfo:
    def __init__(self, name, item_type, evaluate_name):
        self.name = name
        self.item_type = item_type
        self.evaluate_name = evaluate_name # 这是请求 GetDayPlay 时需要的中文名称

def show_venue_page(item_info, parent_window):
    """
    点击项目后打开新的场地数据页面。
    :param item_info: ItemInfo 对象，包含项目数据。
    :param parent_window: 主面板窗口，方便我们操作。
    """
    
    # 假设我们请求的是今天的日期
    from datetime import date, timedelta
    # 获取今天和明天（格式化为字符串）
    today = date.today().strftime("%Y-%m-%d")
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 隐藏主面板窗口
    parent_window.withdraw()
    
    # 创建场地数据窗口
    venue_window = tk.Toplevel()
    venue_window.title(f"{item_info.name} - 场地预定信息")
    venue_window.geometry("800x600")
    
    # 当关闭此窗口时，重新显示主面板
    venue_window.protocol("WM_DELETE_WINDOW", parent_window.deiconify)

    loading_label = tk.Label(venue_window, text=f"正在加载 {item_info.name} ({today}) 的场地数据...", font=("Arial", 14))
    loading_label.pack(pady=50)

    # 启动线程请求场地数据
    threading.Thread(target=thread_fetch_venue_data, 
                     args=(venue_window, loading_label, item_info, tomorrow)).start()

def thread_fetch_venue_data(window, label, item_info, day):
    """后台请求场地数据并渲染"""
    
    success, result = api_handler.get_venue_data(item_info.item_type, item_info.evaluate_name, day)
    print("Fetched venue data:", success, result)
    window.after(0, label.destroy) # 移除加载提示
    
    if success:
        # 在这里渲染场地数据
        render_venue_data(window, item_info.name, result)
    else:
        tk.Label(window, text=f"加载场地数据失败: {result}", fg="red").pack(pady=20)


def render_venue_data(window, item_name, data):
    """
    将场地数据渲染到新窗口中
    注意：这里只是一个骨架，具体渲染需要根据 data 的实际结构来调整。
    """
    tk.Label(window, text=f"项目名称: {item_name}", font=("Arial", 16, "bold")).pack(pady=10)
    
    # 简单地显示 JSON 数据的骨架
    data_text = tk.Text(window, wrap=tk.WORD, height=30, width=100)
    data_text.insert(tk.END, json.dumps(data, indent=4, ensure_ascii=False))
    data_text.pack(padx=20, pady=10)
    
    tk.Label(window, text="请根据以上数据结构设计具体的场地显示界面。", fg="blue").pack()


# --- 修改 thread_login_task: 登录成功后直接打开主面板 ---

def thread_login_task(phone, code):
    success, msg = api_handler.check_login(phone, code)
    
    root.after(0, lambda: login_button.config(text="登 录", state=tk.NORMAL))

    if success:
        root.after(0, lambda: [root.withdraw(), open_dashboard_window()])
    else:
        root.after(0, lambda: messagebox.showerror("登录失败", msg))


# --- 修改 thread_load_dashboard_data: 提取参数 ---

def thread_load_dashboard_data(window, loading_label):
    success, html_content = api_handler.get_dashboard_html()
    
    if not success:
        window.after(0, lambda: loading_label.config(text=f"加载失败: {html_content}"))
        return

    soup = BeautifulSoup(html_content, 'html.parser')
    menu_cont = soup.find('div', class_='menuCont')
    
    items_data = []
    
    if menu_cont:
        for link in menu_cont.find_all('a'):
            name = link.find('p').text.strip() if link.find('p') else "未知项目"
            img_tag = link.find('img')
            img_url = img_tag.get('src') if img_tag else None
            
            # --- 新增逻辑：解析 URL 参数 ---
            href = link.get('href')
            if href:
                # 假设所有链接都是相对路径
                full_url = 'http://example.com' + href 
                query_params = parse_qs(urlparse(full_url).query)
                
                item_type = query_params.get('type', [''])[0]
                
                # 'Evaluate' 参数可能在某些链接中不存在，需要从名称或链接中推断
                # 由于你的 GetDayPlay 接口需要中文名称作为 Evaluate，我们直接使用 'name'
                evaluate_name = name
                
                # 过滤掉不含 type 的链接，如健身
                if not item_type:
                    continue
                
                item_info = ItemInfo(name, item_type, evaluate_name)
            # --- 新增逻辑结束 ---
            else:
                continue

            img_bytes = None
            if img_url:
                img_bytes = api_handler.fetch_image_bytes(img_url)
            
            items_data.append({
                "name": name,
                "img_bytes": img_bytes,
                "item_info": item_info # 存储 ItemInfo 对象
            })
    else:
         window.after(0, lambda: loading_label.config(text="未找到菜单内容，请检查 Cookie 是否有效。"))
         return

    window.after(0, lambda: render_dashboard_ui(window, loading_label, items_data))


# --- 界面构建 (保持不变) ---
root = tk.Tk()
root.title("用户登录/验证")
root.geometry("320x160") 
root.resizable(False, False) 

tk.Label(root, text="手机号:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
phone_entry = tk.Entry(root, width=20) 
phone_entry.grid(row=0, column=1, padx=10, pady=10, columnspan=2, sticky="ew") 

tk.Label(root, text="验证码:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
code_entry = tk.Entry(root, width=10) 
code_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

send_button = tk.Button(root, text="发送验证码", command=handle_send_code)
send_button.grid(row=1, column=2, padx=10, pady=10, sticky="e")

login_button = tk.Button(root, text="登 录", command=handle_login, 
                         width=20, font=('Arial', 10, 'bold'),
                         bg='#4CAF50', fg='white')
login_button.grid(row=2, column=0, columnspan=3, padx=10, pady=(5, 10), sticky="ew") 

root.grid_columnconfigure(1, weight=1) 
root.mainloop()
