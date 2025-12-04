import json
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk 
from bs4 import BeautifulSoup
import io
import re
import threading
import functools
from urllib.parse import urlparse, parse_qs
import api_handler

# --- 全局变量 ---
# 用于防止图片对象被 Python 的垃圾回收机制回收
image_references = [] 

# --- 数据类 ---
class ItemInfo:
    def __init__(self, name, item_type, evaluate_name):
        self.name = name
        self.item_type = item_type
        self.evaluate_name = evaluate_name 

# --- 复杂的表格选择窗口类 ---
class VenueSelectionWindow(tk.Toplevel):
    def __init__(self, parent, item_name, area_name, date_str, venue_data, submit_callback):
        super().__init__(parent)
        self.title(f"{item_name} - {date_str}")
        self.geometry("1100x700") 
        
        self.venue_data = venue_data
        self.submit_callback = submit_callback
        self.selected_items = [] # 存储选中的对象
        self.buttons = {} # 存储按钮引用 (row, col) -> button

        # 1. 解析数据，提取行头（时间）和列头（场地名）
        self.times = self._get_all_times()
        self.venues = [v['name'] for v in venue_data]
        
        # 2. 界面布局
        self._setup_ui(item_name, area_name, date_str)

    def _get_all_times(self):
        # 生成 07:00 到 21:00 的时间列表
        times = []
        for start_hour in range(7, 22):
            t = f"{start_hour:02d}:00"
            times.append(t)
        return times

    def _setup_ui(self, item_name, area_name, date_str):
        # --- 顶部信息栏 ---
        top_frame = tk.Frame(self, pady=10)
        top_frame.pack(fill="x")
        
        tk.Label(top_frame, text=f"项目: {item_name}", font=("微软雅黑", 12, "bold")).pack(side="left", padx=20)
        tk.Label(top_frame, text=f"当前区域: {area_name}", font=("微软雅黑", 12), fg="#333").pack(side="left", padx=10)
        tk.Label(top_frame, text=f"日期: {date_str}", font=("微软雅黑", 12, "bold"), fg="blue").pack(side="left", padx=10)
        
        # 图例
        legend_frame = tk.Frame(top_frame)
        legend_frame.pack(side="right", padx=20)
        self._create_legend(legend_frame, "可预约", "#ffffff") 
        self._create_legend(legend_frame, "已选中", "#90EE90") 
        self._create_legend(legend_frame, "不可约", "#D3D3D3") # 浅灰
        self._create_legend(legend_frame, "已占用", "#87CEFA") # 浅蓝

        # --- 底部提交栏 ---
        bottom_frame = tk.Frame(self, pady=10, bg="#f5f5f5")
        bottom_frame.pack(side="bottom", fill="x")
        
        self.info_label = tk.Label(bottom_frame, text="已选择 0 个场地，总计: ￥0.00", font=("微软雅黑", 11, "bold"), bg="#f5f5f5")
        self.info_label.pack(side="left", padx=20)
        
        btn_submit = tk.Button(bottom_frame, text="提交订单", bg="#4CAF50", fg="white", 
                               font=("微软雅黑", 12, "bold"), command=self._on_submit, padx=20)
        btn_submit.pack(side="right", padx=20)

        # --- 中间滚动表格区域 (Canvas + Scrollbars) ---
        self._create_grid_area()

    def _create_legend(self, parent, text, color):
        f = tk.Frame(parent)
        f.pack(side="left", padx=8)
        tk.Label(f, width=4, bg=color, relief="solid", bd=1).pack(side="left")
        tk.Label(f, text=text, font=("微软雅黑", 9)).pack(side="left", padx=2)

    def _create_grid_area(self):
        # 容器 Frame
        container = tk.Frame(self)
        container.pack(fill="both", expand=True, padx=10, pady=5)

        # 滚动条
        v_scroll = tk.Scrollbar(container, orient="vertical")
        h_scroll = tk.Scrollbar(container, orient="horizontal")
        
        # Canvas
        canvas = tk.Canvas(container, yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set, bg="#e0e0e0")
        v_scroll.config(command=canvas.yview)
        h_scroll.config(command=canvas.xview)

        v_scroll.pack(side="right", fill="y")
        h_scroll.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True)

        # 内部 Frame (放置网格)
        self.grid_frame = tk.Frame(canvas)
        # 在 Canvas 上创建窗口
        canvas_window = canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")

        # 绑定事件：当内部 Frame 大小改变时，更新 Canvas 滚动区域
        def configure_scroll_region(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self.grid_frame.bind("<Configure>", configure_scroll_region)

        # --- 绘制表头 ---
        
        # 左上角空白
        tk.Label(self.grid_frame, text="时间", width=8, height=2, relief="raised", bg="#ddd").grid(row=0, column=0, sticky="nsew")
        
        # 横向表头：场地名称
        for col_idx, venue in enumerate(self.venues):
            lbl = tk.Label(self.grid_frame, text=venue, width=12, height=2, relief="raised", bg="#ddd", wraplength=90)
            lbl.grid(row=0, column=col_idx+1, sticky="nsew")

        # 纵向表头：时间段
        for row_idx, time_slot in enumerate(self.times):
            lbl = tk.Label(self.grid_frame, text=time_slot, width=8, height=3, relief="raised", bg="#ddd")
            lbl.grid(row=row_idx+1, column=0, sticky="nsew")

        # --- 绘制单元格 ---
        for col_idx, venue_obj in enumerate(self.venue_data):
            # 将该场地的所有时间段转为字典: "07:00" -> object
            time_map = {item['TicketLevelName']: item for item in venue_obj['rtnlist']}
            
            for row_idx, time_slot in enumerate(self.times):
                
                cell_data = time_map.get(time_slot)
                
                # 默认样式
                bg_color = "#ffffff" 
                state = tk.NORMAL
                text = "--"
                
                is_clickable = False
                
                if cell_data:
                    text = f"￥{cell_data['MemberPrice']}"
                    
                    # --- 状态判断逻辑 ---
                    if cell_data.get('CDefault7') == "不可预约":
                        bg_color = "#D3D3D3" # 灰色
                        text = "不可预约"
                        state = tk.DISABLED
                    elif str(cell_data.get('CDefault8')) == "1":
                        bg_color = "#87CEFA" # 蓝色
                        text = "已占用"
                        state = tk.DISABLED
                    elif cell_data.get('Description') == "锁场":
                        bg_color = "#D3D3D3" 
                        text = "锁场"
                        state = tk.DISABLED
                    else:
                        # 可预约
                        is_clickable = True
                        bg_color = "#ffffff" 
                else:
                    bg_color = "#D3D3D3"
                    text = ""
                    state = tk.DISABLED
                
                # 创建按钮
                btn = tk.Button(self.grid_frame, text=text, bg=bg_color, width=10, height=3, relief="groove")
                
                if is_clickable:
                    # 使用 partial 固定参数
                    btn.config(command=functools.partial(self._on_cell_click, btn, cell_data, venue_obj['name']))
                else:
                    btn.config(state=tk.DISABLED, fg="#555")

                btn.grid(row=row_idx+1, column=col_idx+1, padx=1, pady=1, sticky="nsew")
                
                self.buttons[(row_idx, col_idx)] = btn

    def _on_cell_click(self, btn, cell_data, venue_name):
        """处理单元格点击"""
        # 唯一标识符
        item_id = (cell_data['TicketTypeNo'], cell_data['TicketLevelNo'])
        
        # 检查是否已存在
        found_index = -1
        for i, item in enumerate(self.selected_items):
            if (item['data']['TicketTypeNo'], item['data']['TicketLevelNo']) == item_id:
                found_index = i
                break
        
        if found_index != -1:
            # 取消选中
            self.selected_items.pop(found_index)
            btn.config(bg="#ffffff") 
        else:
            # 选中
            # 限制选择数量（可选，此处不限制）
            selection_obj = {
                "venue_name": venue_name,
                "time": cell_data['TicketLevelName'],
                "price": cell_data['MemberPrice'],
                "data": cell_data # 原始数据
            }
            self.selected_items.append(selection_obj)
            btn.config(bg="#90EE90") # 绿色
            
        self._update_footer_info()

    def _update_footer_info(self):
        count = len(self.selected_items)
        total_price = sum(float(x['price']) for x in self.selected_items)
        self.info_label.config(text=f"已选择 {count} 个场地，总计: ￥{total_price:.2f}")

    def _on_submit(self):
        if not self.selected_items:
            messagebox.showwarning("提示", "请至少选择一个场地")
            return
        
        self.submit_callback(self.selected_items)
        self.destroy()

# --- 业务逻辑：发送验证码 ---
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
    
    dashboard.protocol("WM_DELETE_WINDOW", root.destroy)
    
    loading_label = tk.Label(dashboard, text="正在加载数据...", font=("Arial", 14))
    loading_label.pack(pady=50)
    
    threading.Thread(target=thread_load_dashboard_data, args=(dashboard, loading_label)).start()

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
            
            # 解析 URL 参数
            href = link.get('href')
            if href:
                full_url = 'http://example.com' + href 
                query_params = parse_qs(urlparse(full_url).query)
                
                item_type = query_params.get('type', [''])[0]
                
                # 默认使用名称作为 Evaluate 参数（后续会从页面解析更准确的）
                evaluate_name = name
                
                if not item_type:
                    continue
                
                item_info = ItemInfo(name, item_type, evaluate_name)
            else:
                continue

            img_bytes = None
            if img_url:
                img_bytes = api_handler.fetch_image_bytes(img_url)
            
            items_data.append({
                "name": name,
                "img_bytes": img_bytes,
                "item_info": item_info 
            })
    else:
         window.after(0, lambda: loading_label.config(text="未找到菜单内容，请检查 Cookie 是否有效。"))
         return

    window.after(0, lambda: render_dashboard_ui(window, loading_label, items_data))

def render_dashboard_ui(window, loading_label, items_data):
    loading_label.destroy()
    container = tk.Frame(window)
    container.pack(expand=True, fill='both', padx=20, pady=20)

    columns = 3 
    
    for i, item in enumerate(items_data):
        row = i // columns
        col = i % columns
        
        click_command = lambda i=item["item_info"]: show_venue_page(i, window)
        
        # --- 使用原生 compound 属性避免闪烁 ---
        card = tk.Button(container, 
                         text=item["name"], 
                         command=click_command,
                         font=("微软雅黑", 10),
                         bg="#f0f0f0",
                         bd=2,
                         relief="raised",
                         width=20,    
                         height=6)

        if item["img_bytes"]:
            try:
                pil_image = Image.open(io.BytesIO(item["img_bytes"]))
                pil_image = pil_image.resize((50, 50), Image.Resampling.LANCZOS)
                tk_image = ImageTk.PhotoImage(pil_image)
                image_references.append(tk_image)
                
                # 图片在文字上方
                card.config(image=tk_image, compound="top", height=100, width=150) 
            except Exception as e:
                card.config(text=f"[图裂]\n{item['name']}")
        
        card.grid(row=row, column=col, padx=10, pady=10)

    for x in range(columns):
        container.grid_columnconfigure(x, weight=1)

# --- 选座流程逻辑 ---

def show_venue_page(item_info, parent_window):
    """
    点击项目后打开新的场地数据页面。
    流程：
    1. 打开窗口
    2. 请求 particulars 页面获取日期和场地列表
    3. 使用获取到的第一个日期和场地，请求具体数据
    """
    parent_window.withdraw()
    
    venue_window = tk.Toplevel()
    venue_window.title(f"{item_info.name} - 场地预定信息")
    venue_window.geometry("800x600")
    venue_window.protocol("WM_DELETE_WINDOW", parent_window.deiconify)

    loading_label = tk.Label(venue_window, text=f"正在获取 {item_info.name} 的配置信息...", font=("Arial", 14))
    loading_label.pack(pady=50)

    threading.Thread(target=thread_process_venue_flow, 
                     args=(venue_window, loading_label, item_info)).start()

def thread_process_venue_flow(window, label, item_info):
    """后台线程：获取配置 -> 获取具体数据"""
    
    # Step 1: 获取 particualrs 页面信息
    success_opt, result_opt = api_handler.get_booking_options(item_info.item_type)
    
    if not success_opt:
        window.after(0, lambda: label.config(text=f"获取配置失败: {result_opt}", fg="red"))
        return

    default_date = result_opt['default_date']
    default_area = result_opt['default_area']
    # all_areas = result_opt['areas'] 
    
    window.after(0, lambda: label.config(text=f"获取成功。\n锁定日期: {default_date}\n锁定场地: {default_area}\n正在加载场地详情..."))
    
    # Step 2: 使用获取到的参数请求具体数据
    success_data, result_data = api_handler.get_venue_data(item_info.item_type, default_area, default_date)
    
    window.after(0, label.destroy) # 移除加载提示
    
    if success_data:
        # 弹出复杂的选择窗口
        window.after(0, lambda: render_venue_data(window, item_info.name, default_area, default_date, result_data))
    else:
        window.after(0, lambda: tk.Label(window, text=f"加载场地数据失败: {result_data}", fg="red").pack(pady=20))

def render_venue_data(window, item_name, area_name, date_str, data_json):
    """
    弹出一个高级选择窗口 (VenueSelectionWindow)
    """
    def on_submit_booking(selected_list):
        # 打印调试
        print("用户选择了以下场地进行预订:")
        # print(json.dumps(selected_list, indent=4, ensure_ascii=False))
        
        # 提示用户
        msg = f"准备为以下时间段提交订单:\n"
        for item in selected_list:
            msg += f"- {item['venue_name']} {item['time']} (￥{item['price']})\n"
        msg += "\n(在此处接入 ChackOrder 接口)"
        
        messagebox.showinfo("提交模拟", msg)
        
        # TODO: 这里编写 api_handler.submit_order(selected_list) 的调用

    # 创建并显示选择窗口
    selector = VenueSelectionWindow(window, item_name, area_name, date_str, data_json, on_submit_booking)
    
    # 保持窗口焦点 (模态)
    selector.transient(window)
    selector.grab_set()
    window.wait_window(selector)

# --- 主程序入口 ---
if __name__ == "__main__":
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