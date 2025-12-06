import json
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from PIL import Image, ImageTk
from bs4 import BeautifulSoup
import io
import re
import threading
import functools
from urllib.parse import urlparse, parse_qs
import os

# --- 自定义模块引用 ---
import api_handler
import task_manager

# --- 全局变量 ---
image_references = [] 

# --- 数据传递类 ---
class ItemInfo:
    def __init__(self, name, item_type, evaluate_name):
        self.name = name
        self.item_type = item_type
        self.evaluate_name = evaluate_name 

# =============================================================================
#  Window A：场地预定/抢票设置窗口 (保持不变)
# =============================================================================
class VenueSelectionWindow(tk.Toplevel):
    def __init__(self, parent_root, item_info, initial_area, initial_date, 
                 all_areas, all_dates, initial_data, submit_callback):
        super().__init__()
        self.parent_root = parent_root
        self.item_info = item_info
        self.submit_callback = submit_callback
        
        # 数据状态
        self.current_area = initial_area
        self.current_date = initial_date
        self.all_areas = all_areas
        self.all_dates = all_dates
        self.venue_data = initial_data
        
        self.selected_items = []
        self.buttons = {} 

        self.title(f"{item_info.name} - 抢票任务设置")
        self.geometry("1200x800")

        try: 
            # Windows
            self.state('zoomed')  
        except: 
            try:
                # Linux / Mac
                self.attributes('-zoomed', True) 
            except:
                # 如果都不支持，就不强制最大化，或者使用全屏
                # self.attributes('-fullscreen', True) # 全屏可能会导致没有关闭按钮，慎用
                pass 

        self.times = self._get_all_times()
        self.venues = [v['name'] for v in self.venue_data]

        self._setup_ui()
        
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")
        self.destroy()
        if hasattr(self.parent_root, 'refresh_task_list'):
            self.parent_root.refresh_task_list()
        self.parent_root.deiconify()

    def _on_mousewheel(self, event):
        if hasattr(self, 'canvas'):
            if event.num == 5 or event.delta < 0:
                self.canvas.yview_scroll(1, "units")
            elif event.num == 4 or event.delta > 0:
                self.canvas.yview_scroll(-1, "units")

    def _get_all_times(self):
        times = []
        for start_hour in range(7, 22):
            t = f"{start_hour:02d}:00"
            times.append(t)
        return times

    def _setup_ui(self):
        top_frame = tk.Frame(self, pady=10, bg="#f9f9f9")
        top_frame.pack(fill="x")
        
        tk.Label(top_frame, text=f"项目: {self.item_info.name}", font=("微软雅黑", 14, "bold"), bg="#f9f9f9").pack(side="left", padx=(20, 10))
        
        tk.Label(top_frame, text="日期:", font=("微软雅黑", 10), bg="#f9f9f9").pack(side="left", padx=5)
        self.date_combo = ttk.Combobox(top_frame, values=self.all_dates, state="readonly", width=12)
        self.date_combo.set(self.current_date)
        self.date_combo.pack(side="left", padx=5)
        self.date_combo.bind("<<ComboboxSelected>>", self._on_filter_change)

        tk.Label(top_frame, text="区域:", font=("微软雅黑", 10), bg="#f9f9f9").pack(side="left", padx=(20, 5))
        self.area_combo = ttk.Combobox(top_frame, values=self.all_areas, state="readonly", width=18)
        self.area_combo.set(self.current_area)
        self.area_combo.pack(side="left", padx=5)
        self.area_combo.bind("<<ComboboxSelected>>", self._on_filter_change)
        
        self.loading_label = tk.Label(top_frame, text="数据加载中...", fg="red", bg="#f9f9f9")
        
        legend_frame = tk.Frame(top_frame, bg="#f9f9f9")
        legend_frame.pack(side="right", padx=20)
        self._create_legend(legend_frame, "可预约", "#ffffff") 
        self._create_legend(legend_frame, "本次选中", "#90EE90") 
        self._create_legend(legend_frame, "已设自动抢", "#FFA500") 
        self._create_legend(legend_frame, "不可/占用", "#D3D3D3") 

        bottom_frame = tk.Frame(self, pady=15, bg="#eee")
        bottom_frame.pack(side="bottom", fill="x")
        
        self.info_label = tk.Label(bottom_frame, text="本次已选 0 个场地", font=("微软雅黑", 11, "bold"), bg="#eee")
        self.info_label.pack(side="left", padx=20)
        
        btn_submit = tk.Button(bottom_frame, text="设置自动抢 (次日08:00提交)", bg="#FF8C00", fg="white", 
                               font=("微软雅黑", 12, "bold"), command=self._on_submit_task, padx=20, pady=5)
        btn_submit.pack(side="right", padx=20)

        self.grid_container = tk.Frame(self)
        self.grid_container.pack(fill="both", expand=True, padx=10, pady=5)
        self._draw_grid()

    def _create_legend(self, parent, text, color):
        f = tk.Frame(parent, bg="#f9f9f9")
        f.pack(side="left", padx=10)
        tk.Label(f, width=4, bg=color, relief="solid", bd=1).pack(side="left")
        tk.Label(f, text=text, font=("微软雅黑", 9), bg="#f9f9f9").pack(side="left", padx=3)

    def _on_filter_change(self, event):
        new_date = self.date_combo.get()
        new_area = self.area_combo.get()
        if new_date == self.current_date and new_area == self.current_area: return

        self.date_combo.config(state="disabled")
        self.area_combo.config(state="disabled")
        self.loading_label.pack(side="left", padx=10)
        self.selected_items = []
        self._update_footer_info()
        threading.Thread(target=self._thread_reload_data, args=(new_area, new_date)).start()

    def _thread_reload_data(self, area, date):
        success, result = api_handler.get_venue_data(self.item_info.item_type, area, date)
        self.after(0, lambda: self._finish_reload(success, result, area, date))

    def _finish_reload(self, success, result, area, date):
        self.date_combo.config(state="readonly")
        self.area_combo.config(state="readonly")
        self.loading_label.pack_forget()

        if success:
            self.venue_data = result
            self.current_area = area
            self.current_date = date
            self.venues = [v['name'] for v in self.venue_data] 
            self._draw_grid() 
        else:
            messagebox.showerror("刷新失败", f"接口请求失败: {result}")
            self.date_combo.set(self.current_date)
            self.area_combo.set(self.current_area)

    def _draw_grid(self):
        for widget in self.grid_container.winfo_children(): widget.destroy()

        v_scroll = tk.Scrollbar(self.grid_container, orient="vertical")
        h_scroll = tk.Scrollbar(self.grid_container, orient="horizontal")
        self.canvas = tk.Canvas(self.grid_container, yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set, bg="#e0e0e0")
        v_scroll.config(command=self.canvas.yview)
        h_scroll.config(command=self.canvas.xview)

        v_scroll.pack(side="right", fill="y")
        h_scroll.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.grid_frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")

        def configure_scroll_region(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.grid_frame.bind("<Configure>", configure_scroll_region)

        # 绘制
        tk.Label(self.grid_frame, text="时间", width=8, height=2, relief="raised", bg="#ddd", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="nsew")
        for col_idx, venue in enumerate(self.venues):
            lbl = tk.Label(self.grid_frame, text=venue, width=12, height=2, relief="raised", bg="#ddd", wraplength=90, font=("Arial", 9))
            lbl.grid(row=0, column=col_idx+1, sticky="nsew")
        for row_idx, time_slot in enumerate(self.times):
            lbl = tk.Label(self.grid_frame, text=time_slot, width=8, height=3, relief="raised", bg="#ddd", font=("Arial", 10))
            lbl.grid(row=row_idx+1, column=0, sticky="nsew")

        self.buttons = {}
        saved_tasks = task_manager.load_tasks()
        
        for col_idx, venue_obj in enumerate(self.venue_data):
            time_map = {item['TicketLevelName']: item for item in venue_obj['rtnlist']}
            for row_idx, time_slot in enumerate(self.times):
                cell_data = time_map.get(time_slot)
                
                bg_color = "#ffffff" 
                state = tk.NORMAL
                text = "--"
                is_clickable = False
                
                if cell_data:
                    text = f"￥{cell_data['MemberPrice']}"
                    
                    is_scheduled = False
                    for t in saved_tasks:
                        if (t['date'] == self.current_date and 
                            t['time'] == time_slot and 
                            t['venue_name'] == venue_obj['name'] and
                            t['area_name'] == self.current_area): 
                            is_scheduled = True
                            break
                    
                    if is_scheduled:
                        bg_color = "#FFA500" 
                        text = "已设自动"
                        state = tk.DISABLED 
                    elif cell_data.get('CDefault7') == "不可预约":
                        bg_color = "#D3D3D3" 
                        text = "不可预约"
                        state = tk.DISABLED
                    elif str(cell_data.get('CDefault8')) == "1":
                        bg_color = "#87CEFA"
                        text = "已占用"
                        state = tk.DISABLED
                    elif cell_data.get('Description') == "锁场":
                        bg_color = "#D3D3D3" 
                        text = "锁场"
                        state = tk.DISABLED
                    else:
                        is_clickable = True
                        bg_color = "#ffffff"
                else:
                    bg_color = "#D3D3D3"
                    text = ""
                    state = tk.DISABLED
                
                btn = tk.Button(self.grid_frame, text=text, bg=bg_color, width=10, height=3, relief="groove")
                if is_clickable:
                    btn.config(command=functools.partial(self._on_cell_click, btn, cell_data, venue_obj['name']))
                else:
                    btn.config(state=tk.DISABLED, disabledforeground="#333" if bg_color=="#FFA500" else "#888")

                btn.grid(row=row_idx+1, column=col_idx+1, padx=1, pady=1, sticky="nsew")
                self.buttons[(row_idx, col_idx)] = btn

    def _on_cell_click(self, btn, cell_data, venue_name):
        item_id = (cell_data['TicketTypeNo'], cell_data['TicketLevelNo'])
        found_index = -1
        for i, item in enumerate(self.selected_items):
            if (item['data']['TicketTypeNo'], item['data']['TicketLevelNo']) == item_id:
                found_index = i
                break
        
        if found_index != -1:
            self.selected_items.pop(found_index)
            btn.config(bg="#ffffff") 
        else:
            selection_obj = {
                "venue_name": venue_name,
                "area_name": self.current_area,
                "date": self.current_date, 
                "time": cell_data['TicketLevelName'],
                "price": cell_data['MemberPrice'],
                "data": cell_data
            }
            self.selected_items.append(selection_obj)
            btn.config(bg="#90EE90") 
            
        self._update_footer_info()

    def _update_footer_info(self):
        count = len(self.selected_items)
        total_price = sum(float(x['price']) for x in self.selected_items)
        self.info_label.config(text=f"本次已选 {count} 个场地，总计: ￥{total_price:.2f}")

    def _on_submit_task(self):
        if not self.selected_items:
            messagebox.showwarning("提示", "请至少选择一个绿色场地")
            return
        
        self.submit_callback(self.selected_items)
        self.selected_items = []
        self._update_footer_info()
        self._draw_grid()
        messagebox.showinfo("成功", "抢票任务已添加！\n系统将自动在目标日期尝试抢票。\n请在主界面右侧查看任务列表。")


# =============================================================================
#  主面板窗口 (Dashboard)
# =============================================================================
class DashboardWindow(tk.Toplevel):
    def __init__(self, login_root, user_phone=""):
        super().__init__()
        self.login_root = login_root
        self.user_phone = user_phone
        self.title(f"场馆服务 & 任务管理器 - 用户: {user_phone}")
        self.geometry("1000x700")
        
        self.protocol("WM_DELETE_WINDOW", self.on_exit)
        
        # 布局
        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief="raised")
        paned.pack(fill=tk.BOTH, expand=True)
        
        self.left_frame = tk.Frame(paned, width=650)
        paned.add(self.left_frame, stretch="always")
        
        self.right_frame = tk.Frame(paned, width=350, bg="#f2f2f2")
        paned.add(self.right_frame, stretch="never")
        
        # UI 初始化
        self._init_left_ui()
        self._init_right_ui()
        self._init_status_bar() # 底部状态栏
        
        # 数据加载
        self.load_venues()
        self.refresh_task_list()

    def on_exit(self):
        # 关闭主窗口时彻底退出程序
        self.login_root.destroy()

    def _init_left_ui(self):
        header = tk.Label(self.left_frame, text="在线预订服务", font=("微软雅黑", 16, "bold"), pady=15)
        header.pack()
        
        self.venue_container = tk.Frame(self.left_frame)
        self.venue_container.pack(expand=True, fill='both', padx=20, pady=10)
        
        self.loading_label = tk.Label(self.venue_container, text="正在加载场馆列表...", font=("Arial", 12))
        self.loading_label.pack(pady=50)

    def _init_right_ui(self):
        header = tk.Label(self.right_frame, text="自动抢票任务监控", font=("微软雅黑", 12, "bold"), bg="#f2f2f2", pady=15)
        header.pack(fill="x")
        
        container = tk.Frame(self.right_frame, bg="#f2f2f2")
        container.pack(fill="both", expand=True, padx=10, pady=5)
        
        canvas = tk.Canvas(container, bg="#f2f2f2", highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        
        self.task_list_frame = tk.Frame(canvas, bg="#f2f2f2")
        self.task_list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        
        canvas.create_window((0, 0), window=self.task_list_frame, anchor="nw", width=310)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        btn_refresh = tk.Button(self.right_frame, text="刷新任务状态", command=self.refresh_task_list, bg="#ddd")
        btn_refresh.pack(pady=10, fill="x", padx=10)

    def _init_status_bar(self):
        """底部状态栏：显示用户 + 注销按钮"""
        status_bar = tk.Frame(self, bd=1, relief=tk.SUNKEN, bg="#e1e1e1")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        user_info = f"当前登录: {self.user_phone if self.user_phone else '未知用户'}"
        tk.Label(status_bar, text=user_info, bg="#e1e1e1", font=("Arial", 10)).pack(side=tk.LEFT, padx=10, pady=5)
        
        btn_logout = tk.Button(status_bar, text="注销 / 切换账号", command=self.do_logout, 
                               bg="#FF6347", fg="white", font=("Arial", 9, "bold"), relief="flat", padx=10)
        btn_logout.pack(side=tk.RIGHT, padx=10, pady=2)

    def do_logout(self):
        """执行注销"""
        if messagebox.askyesno("注销", "确定要退出登录吗？\n这将清除自动登录凭证。"):
            api_handler.clear_login_info() # 清除本地文件
            self.destroy() # 关闭主面板
            self.login_root.deiconify() # 显示登录窗口

    # --- 左侧加载逻辑 ---
    def load_venues(self):
        threading.Thread(target=self._thread_load_venues).start()

    def _thread_load_venues(self):
        success, html_content = api_handler.get_dashboard_html()
        if not success:
            self.after(0, lambda: self.loading_label.config(text=f"加载失败: {html_content}"))
            return
        
        soup = BeautifulSoup(html_content, 'html.parser')
        menu_cont = soup.find('div', class_='menuCont')
        items_data = []
        
        if menu_cont:
            for link in menu_cont.find_all('a'):
                name = link.find('p').text.strip() if link.find('p') else "未知项目"
                img_tag = link.find('img')
                img_url = img_tag.get('src') if img_tag else None
                href = link.get('href')
                if href:
                    full_url = 'http://example.com' + href
                    qp = parse_qs(urlparse(full_url).query)
                    item_type = qp.get('type', [''])[0]
                    if not item_type: continue
                    item_info = ItemInfo(name, item_type, name)
                    img_bytes = None
                    if img_url:
                        img_bytes = api_handler.fetch_image_bytes(img_url)
                    items_data.append({"name": name, "img_bytes": img_bytes, "item_info": item_info})
        
        self.after(0, lambda: self._render_venues(items_data))

    def _render_venues(self, items):
        self.loading_label.destroy()
        cols = 3
        for i, item in enumerate(items):
            r, c = divmod(i, cols)
            cmd = lambda info=item["item_info"]: show_venue_page_flow(info, self)
            btn = tk.Button(self.venue_container, text=item["name"], command=cmd,
                            font=("微软雅黑", 10, "bold"), bg="white", relief="raised", bd=2, width=18, height=8)
            if item["img_bytes"]:
                try:
                    pil_img = Image.open(io.BytesIO(item["img_bytes"])).resize((50, 50), Image.Resampling.LANCZOS)
                    tk_img = ImageTk.PhotoImage(pil_img)
                    image_references.append(tk_img)
                    btn.config(image=tk_img, compound="top", width=140, height=100)
                except: pass
            btn.grid(row=r, column=c, padx=15, pady=15)

    # --- 右侧任务逻辑 ---
    def refresh_task_list(self):
        for w in self.task_list_frame.winfo_children(): w.destroy()
        tasks = task_manager.load_tasks()
        if not tasks:
            tk.Label(self.task_list_frame, text="暂无抢票任务", bg="#f2f2f2", fg="#888").pack(pady=20)
            return

        for idx, task in enumerate(tasks):
            card = tk.Frame(self.task_list_frame, bg="white", bd=1, relief="solid")
            card.pack(fill="x", padx=5, pady=5)
            
            info_frame = tk.Frame(card, bg="white")
            info_frame.pack(side="left", padx=10, pady=5)
            
            tk.Label(info_frame, text=f"{task['date']}  {task['time']}", font=("Arial", 10, "bold"), bg="white", fg="#FF8C00").pack(anchor="w")
            tk.Label(info_frame, text=f"{task['venue_name']}", font=("Arial", 9), bg="white").pack(anchor="w")
            tk.Label(info_frame, text=f"区域: {task['area_name']}", font=("Arial", 9, "italic"), bg="white", fg="#666").pack(anchor="w")
            
            btn_del = tk.Button(card, text="取消", bg="#FF6347", fg="white", font=("Arial", 9), 
                                relief="flat", command=lambda i=idx: self._delete_task(i))
            btn_del.pack(side="right", padx=10, pady=10)

    def _delete_task(self, index):
        if messagebox.askyesno("确认", "确定要取消这个自动抢票任务吗？"):
            task_manager.delete_task(index)
            self.refresh_task_list()


# =============================================================================
#  加载流程控制
# =============================================================================

def show_venue_page_flow(item_info, dashboard_window):
    """
    流程入口：
    1. 隐藏主 Dashboard
    2. 显示临时 Loading 窗口 (禁止关闭)
    3. 后台请求数据
    """
    dashboard_window.withdraw()
    
    loading_win = tk.Toplevel()
    loading_win.title("请稍候")
    loading_win.geometry("300x120")
    
    # 居中显示
    screen_width = loading_win.winfo_screenwidth()
    screen_height = loading_win.winfo_screenheight()
    loading_win.geometry(f"+{(screen_width - 300) // 2}+{(screen_height - 120) // 2}")
    
    # --- 关键修复 1: 禁止用户手动关闭加载窗口，防止报错中断流程 ---
    loading_win.protocol("WM_DELETE_WINDOW", lambda: None)
    
    tk.Label(loading_win, text=f"正在连接 {item_info.name}...", font=("微软雅黑", 11)).pack(pady=15)
    tk.Label(loading_win, text="获取未来7天数据中...", fg="#666").pack()

    # 启动后台线程
    threading.Thread(target=thread_process_data, 
                     args=(loading_win, dashboard_window, item_info)).start()

def thread_process_data(loading_win, dashboard_window, item_info):
    """
    后台线程：执行耗时操作
    增加了全局 try-except，确保无论发生什么错误，都能恢复主窗口显示
    """
    try:
        # 1. 获取配置
        success_opt, result_opt = api_handler.get_booking_options(item_info.item_type)
        
        if not success_opt:
            # 失败处理：回到主线程报错并恢复主窗口
            loading_win.after(0, lambda: _handle_error(loading_win, dashboard_window, f"获取配置失败: {result_opt}"))
            return

        default_date = result_opt['default_date']
        default_area = result_opt['default_area']
        all_dates = api_handler.get_next_7_days() 
        all_areas = result_opt['areas']
        target_date = all_dates[0]
        
        # 2. 获取具体数据
        success_data, result_data = api_handler.get_venue_data(item_info.item_type, default_area, target_date)
        
        if not success_data:
            loading_win.after(0, lambda: _handle_error(loading_win, dashboard_window, f"加载数据异常: {result_data}"))
            return

        # 3. 成功：在主线程打开选择窗口
        loading_win.after(0, lambda: open_selection_window(
            loading_win, dashboard_window, 
            item_info, default_area, target_date, 
            all_areas, all_dates, result_data
        ))

    except Exception as e:
        print(f"线程内部严重错误: {e}")
        # 发生未捕获异常时，务必恢复界面
        loading_win.after(0, lambda: _handle_error(loading_win, dashboard_window, f"系统错误: {str(e)}"))

def _handle_error(loading_win, dashboard_window, msg):
    """辅助函数：处理错误并恢复主界面"""
    try:
        loading_win.destroy()
    except:
        pass
    messagebox.showerror("错误", msg)
    dashboard_window.deiconify() # 重新显示主窗口        

def open_selection_window(loading_win, dashboard_window, item_info, area, date, all_areas, all_dates, data):
    """实例化窗口 A"""
    
    # 先销毁加载窗口
    try:
        loading_win.destroy()
    except:
        pass

    def on_save_tasks(selected_list):
        if selected_list:
            task_manager.save_task(selected_list)
    
    # --- 关键修复 2: 实例化窗口时增加保护，防止 init 崩溃导致主窗口消失 ---
    try:
        VenueSelectionWindow(dashboard_window, item_info, area, date, 
                             all_areas, all_dates, data, on_save_tasks)
    except Exception as e:
        messagebox.showerror("界面错误", f"无法打开预订窗口: {e}")
        dashboard_window.deiconify() # 救命稻草：显示回主窗口


# =============================================================================
#  登录逻辑
# =============================================================================

def handle_send_code():
    phone = phone_entry.get()
    if not re.fullmatch(r'1\d{10}', phone):
        messagebox.showwarning("输入错误", "请输入有效的11位手机号码")
        return
    
    send_button.config(state=tk.DISABLED, text="发送中...")
    
    def _send():
        success, msg = api_handler.send_sms_code(phone)
        if success:
            root.after(0, lambda: [messagebox.showinfo("成功", "验证码已发送"), start_countdown()])
        else:
            root.after(0, lambda: [messagebox.showerror("失败", msg), send_button.config(state=tk.NORMAL, text="发送验证码")])
            
    threading.Thread(target=_send).start()

def start_countdown(remaining=60):
    if remaining > 0:
        send_button.config(text=f"{remaining}s", state=tk.DISABLED)
        root.after(1000, start_countdown, remaining - 1)
    else:
        send_button.config(text="发送验证码", state=tk.NORMAL)

def handle_login():
    phone = phone_entry.get()
    code = code_entry.get()
    if not re.fullmatch(r'1\d{10}', phone):
        messagebox.showwarning("提示", "手机号格式错误")
        return
    if not code:
        messagebox.showwarning("提示", "请输入验证码")
        return
    
    login_button.config(text="登录中...", state=tk.DISABLED)
    
    def _login():
        success, msg = api_handler.check_login(phone, code)
        root.after(0, lambda: login_button.config(text="登 录", state=tk.NORMAL))
        if success:
            # 登录成功，保存手机号
            api_handler.save_user_phone(phone)
            root.after(0, lambda: [root.withdraw(), DashboardWindow(root, phone)])
        else:
            root.after(0, lambda: messagebox.showerror("登录失败", msg))
            
    threading.Thread(target=_login).start()

# =============================================================================
#  程序入口：自动登录检查
# =============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    root.title("用户登录")
    root.geometry("350x200") 
    root.resizable(False, False) 
    
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"+{(sw-350)//2}+{(sh-200)//2}")

    # UI 布局
    main_frame = tk.Frame(root, padx=20, pady=20)
    main_frame.pack(fill="both", expand=True)

    tk.Label(main_frame, text="手机号:", font=("微软雅黑", 10)).grid(row=0, column=0, pady=10, sticky="w")
    phone_entry = tk.Entry(main_frame, width=22) 
    phone_entry.grid(row=0, column=1, columnspan=2, pady=10, sticky="w") 

    tk.Label(main_frame, text="验证码:", font=("微软雅黑", 10)).grid(row=1, column=0, pady=10, sticky="w")
    code_entry = tk.Entry(main_frame, width=10) 
    code_entry.grid(row=1, column=1, pady=10, sticky="w")

    send_button = tk.Button(main_frame, text="发送验证码", command=handle_send_code, font=("微软雅黑", 9))
    send_button.grid(row=1, column=2, pady=10, sticky="e")

    login_button = tk.Button(main_frame, text="登 录", command=handle_login, 
                             width=25, font=('微软雅黑', 11, 'bold'),
                             bg='#4CAF50', fg='white', relief="flat")
    login_button.grid(row=2, column=0, columnspan=3, pady=20) 

    # --- 自动登录检查逻辑 ---
    def check_auto_login():
        print("检查自动登录...")
        saved_phone = api_handler.get_current_user()
        if saved_phone:
            print(f"发现已保存用户: {saved_phone}，验证 Session...")
            # 验证 Session 是否有效
            if api_handler.validate_session():
                print("Session 有效，跳过登录")
                root.withdraw()
                DashboardWindow(root, saved_phone)
            else:
                print("Session 失效，请重新登录")
                # 预填充手机号
                phone_entry.insert(0, saved_phone)
        else:
            print("无保存用户")

    # 稍微延迟一下执行检查，让界面先初始化
    root.after(100, check_auto_login)

    root.mainloop()