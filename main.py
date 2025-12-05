import json
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk  # 引入 ttk 用于下拉框和更现代的控件
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
# 用于防止图片对象被 Python 的垃圾回收机制回收
image_references = [] 

# --- 数据传递类 ---
class ItemInfo:
    def __init__(self, name, item_type, evaluate_name):
        self.name = name
        self.item_type = item_type
        self.evaluate_name = evaluate_name 

# =============================================================================
#  窗口 A：场地预定/抢票设置窗口 (支持滚轮、下拉筛选、自动抢状态回显)
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
        
        self.selected_items = [] # 当前手动选中的(绿色)
        self.buttons = {} 

        # 窗口基本设置
        self.title(f"{item_info.name} - 抢票任务设置")
        self.geometry("1200x800")
        
        # 尝试最大化窗口
        try: 
            self.state('zoomed')  # Windows
        except: 
            try:
                self.attributes('-zoomed', True) # Linux
            except:
                self.attributes('-fullscreen', True) # 备选

        # 预生成时间轴 (07:00 - 21:00)
        self.times = self._get_all_times()
        self.venues = [v['name'] for v in self.venue_data]

        # 初始化界面
        self._setup_ui()
        
        # 绑定鼠标滚轮 (支持 Windows, Linux, MacOS)
        # 注意：这里绑定到 grid_container 内部的 canvas 上，或者是全局绑定
        self.bind_all("<MouseWheel>", self._on_mousewheel)  # Windows / MacOS
        self.bind_all("<Button-4>", self._on_mousewheel)    # Linux scroll up
        self.bind_all("<Button-5>", self._on_mousewheel)    # Linux scroll down

        # 窗口关闭时解绑滚轮事件并刷新主界面任务列表
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        # 解绑全局事件以免影响其他窗口
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")
        self.destroy()
        
        # 调用父级(Dashboard)的刷新方法
        if hasattr(self.parent_root, 'refresh_task_list'):
            self.parent_root.refresh_task_list()
        self.parent_root.deiconify()

    def _on_mousewheel(self, event):
        # 只有当 Canvas 存在时才滚动
        if hasattr(self, 'canvas'):
            # Windows: event.delta, Linux: event.num
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
        # --- 1. 顶部控制栏 ---
        top_frame = tk.Frame(self, pady=10, bg="#f9f9f9")
        top_frame.pack(fill="x")
        
        tk.Label(top_frame, text=f"项目: {self.item_info.name}", font=("微软雅黑", 14, "bold"), bg="#f9f9f9").pack(side="left", padx=(20, 10))
        
        # 日期选择
        tk.Label(top_frame, text="日期:", font=("微软雅黑", 10), bg="#f9f9f9").pack(side="left", padx=5)
        self.date_combo = ttk.Combobox(top_frame, values=self.all_dates, state="readonly", width=12, font=("Arial", 10))
        self.date_combo.set(self.current_date)
        self.date_combo.pack(side="left", padx=5)
        self.date_combo.bind("<<ComboboxSelected>>", self._on_filter_change)

        # 区域选择
        tk.Label(top_frame, text="区域:", font=("微软雅黑", 10), bg="#f9f9f9").pack(side="left", padx=(20, 5))
        self.area_combo = ttk.Combobox(top_frame, values=self.all_areas, state="readonly", width=18, font=("Arial", 10))
        self.area_combo.set(self.current_area)
        self.area_combo.pack(side="left", padx=5)
        self.area_combo.bind("<<ComboboxSelected>>", self._on_filter_change)
        
        # 加载提示
        self.loading_label = tk.Label(top_frame, text="数据加载中...", fg="red", bg="#f9f9f9")
        
        # 图例说明
        legend_frame = tk.Frame(top_frame, bg="#f9f9f9")
        legend_frame.pack(side="right", padx=20)
        self._create_legend(legend_frame, "可预约", "#ffffff") 
        self._create_legend(legend_frame, "本次选中", "#90EE90") # 绿色
        self._create_legend(legend_frame, "已设自动抢", "#FFA500") # 橙色
        self._create_legend(legend_frame, "不可/占用", "#D3D3D3") # 灰色

        # --- 2. 底部提交栏 ---
        bottom_frame = tk.Frame(self, pady=15, bg="#eee")
        bottom_frame.pack(side="bottom", fill="x")
        
        self.info_label = tk.Label(bottom_frame, text="本次已选 0 个场地", font=("微软雅黑", 11, "bold"), bg="#eee")
        self.info_label.pack(side="left", padx=20)
        
        # 核心按钮：设置自动抢
        btn_submit = tk.Button(bottom_frame, text="设置自动抢 (次日08:00提交)", bg="#FF8C00", fg="white", 
                               font=("微软雅黑", 12, "bold"), command=self._on_submit_task, padx=20, pady=5)
        btn_submit.pack(side="right", padx=20)

        # --- 3. 中间表格容器 (Canvas + Scrollbar) ---
        self.grid_container = tk.Frame(self)
        self.grid_container.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 初次绘制
        self._draw_grid()

    def _create_legend(self, parent, text, color):
        f = tk.Frame(parent, bg="#f9f9f9")
        f.pack(side="left", padx=10)
        tk.Label(f, width=4, bg=color, relief="solid", bd=1).pack(side="left")
        tk.Label(f, text=text, font=("微软雅黑", 9), bg="#f9f9f9").pack(side="left", padx=3)

    def _on_filter_change(self, event):
        """当日期或区域改变时，后台刷新数据"""
        new_date = self.date_combo.get()
        new_area = self.area_combo.get()
        
        if new_date == self.current_date and new_area == self.current_area:
            return

        # 锁定控件
        self.date_combo.config(state="disabled")
        self.area_combo.config(state="disabled")
        self.loading_label.pack(side="left", padx=10)
        
        # 清空当前未保存的选择
        self.selected_items = []
        self._update_footer_info()

        # 启动线程
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
            self.venues = [v['name'] for v in self.venue_data] # 更新列头
            self._draw_grid() # 重绘
        else:
            messagebox.showerror("刷新失败", f"接口请求失败: {result}")
            # 回滚选项
            self.date_combo.set(self.current_date)
            self.area_combo.set(self.current_area)

    def _draw_grid(self):
        """绘制表格的核心逻辑"""
        # 清空旧内容
        for widget in self.grid_container.winfo_children():
            widget.destroy()

        # 创建 Canvas 结构
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

        # --- 绘制内容 ---
        
        # 1. 绘制表头 (列：场地名)
        tk.Label(self.grid_frame, text="时间", width=8, height=2, relief="raised", bg="#ddd", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="nsew")
        for col_idx, venue in enumerate(self.venues):
            lbl = tk.Label(self.grid_frame, text=venue, width=12, height=2, relief="raised", bg="#ddd", wraplength=90, font=("Arial", 9))
            lbl.grid(row=0, column=col_idx+1, sticky="nsew")

        # 2. 绘制行头 (行：时间)
        for row_idx, time_slot in enumerate(self.times):
            lbl = tk.Label(self.grid_frame, text=time_slot, width=8, height=3, relief="raised", bg="#ddd", font=("Arial", 10))
            lbl.grid(row=row_idx+1, column=0, sticky="nsew")

        # 3. 绘制单元格
        self.buttons = {}
        
        # 获取本地已保存的任务，用于回显 (Orange)
        # 这里为了简化，我们重新加载所有任务进行比对
        saved_tasks = task_manager.load_tasks()
        
        for col_idx, venue_obj in enumerate(self.venue_data):
            # 将该场地的所有时间段转为字典
            time_map = {item['TicketLevelName']: item for item in venue_obj['rtnlist']}
            
            for row_idx, time_slot in enumerate(self.times):
                cell_data = time_map.get(time_slot)
                
                # 默认状态
                bg_color = "#ffffff" 
                state = tk.NORMAL
                text = "--"
                is_clickable = False
                
                if cell_data:
                    text = f"￥{cell_data['MemberPrice']}"
                    
                    # --- 状态判断优先级 ---
                    
                    # 1. 检查是否已经在自动抢任务列表中
                    is_scheduled = False
                    for t in saved_tasks:
                        if (t['date'] == self.current_date and 
                            t['time'] == time_slot and 
                            t['venue_name'] == venue_obj['name'] and
                            t['area_name'] == self.current_area): # 需精确匹配区域
                            is_scheduled = True
                            break
                    
                    if is_scheduled:
                        bg_color = "#FFA500" # 橙色
                        text = "已设自动"
                        state = tk.DISABLED # 已设置的不允许在当前界面重复点击，需去主界面取消
                    
                    # 2. 检查 API 返回的占用状态
                    elif cell_data.get('CDefault7') == "不可预约":
                        bg_color = "#D3D3D3" # 灰色
                        text = "不可预约"
                        state = tk.DISABLED
                    elif str(cell_data.get('CDefault8')) == "1":
                        bg_color = "#87CEFA" # 浅蓝
                        text = "已占用"
                        state = tk.DISABLED
                    elif cell_data.get('Description') == "锁场":
                        bg_color = "#D3D3D3" 
                        text = "锁场"
                        state = tk.DISABLED
                    else:
                        # 3. 可预约状态
                        is_clickable = True
                        bg_color = "#ffffff"
                else:
                    bg_color = "#D3D3D3"
                    text = ""
                    state = tk.DISABLED
                
                btn = tk.Button(self.grid_frame, text=text, bg=bg_color, width=10, height=3, relief="groove")
                
                if is_clickable:
                    # 绑定点击事件
                    btn.config(command=functools.partial(self._on_cell_click, btn, cell_data, venue_obj['name']))
                else:
                    btn.config(state=tk.DISABLED, disabledforeground="#333" if bg_color=="#FFA500" else "#888")

                btn.grid(row=row_idx+1, column=col_idx+1, padx=1, pady=1, sticky="nsew")
                self.buttons[(row_idx, col_idx)] = btn

    def _on_cell_click(self, btn, cell_data, venue_name):
        """处理单元格点击：绿色选中/白色取消"""
        item_id = (cell_data['TicketTypeNo'], cell_data['TicketLevelNo'])
        
        found_index = -1
        for i, item in enumerate(self.selected_items):
            if (item['data']['TicketTypeNo'], item['data']['TicketLevelNo']) == item_id:
                found_index = i
                break
        
        if found_index != -1:
            # 已存在 -> 取消选中
            self.selected_items.pop(found_index)
            btn.config(bg="#ffffff") 
        else:
            # 未存在 -> 选中
            selection_obj = {
                "venue_name": venue_name,
                "area_name": self.current_area, # 关键：保存区域信息
                "date": self.current_date, 
                "time": cell_data['TicketLevelName'],
                "price": cell_data['MemberPrice'],
                "data": cell_data
            }
            self.selected_items.append(selection_obj)
            btn.config(bg="#90EE90") # 变绿
            
        self._update_footer_info()

    def _update_footer_info(self):
        count = len(self.selected_items)
        total_price = sum(float(x['price']) for x in self.selected_items)
        self.info_label.config(text=f"本次已选 {count} 个场地，总计: ￥{total_price:.2f}")

    def _on_submit_task(self):
        if not self.selected_items:
            messagebox.showwarning("提示", "请至少选择一个绿色场地")
            return
        
        # 将数据传回回调函数 (保存到本地)
        self.submit_callback(self.selected_items)
        
        # 清空当前选择
        self.selected_items = []
        self._update_footer_info()
        
        # 刷新视图 (让刚才选中的变橙色)
        self._draw_grid()
        
        messagebox.showinfo("成功", "抢票任务已添加！\n系统将自动在目标日期尝试抢票。\n请在主界面右侧查看任务列表。")


# =============================================================================
#  主面板窗口 (Dashboard)：左右分栏
# =============================================================================
class DashboardWindow(tk.Toplevel):
    def __init__(self, login_root):
        super().__init__()
        self.login_root = login_root
        self.title("场馆服务 & 自动抢票任务管理器")
        self.geometry("1000x700")
        
        # 关闭主面板时退出程序
        self.protocol("WM_DELETE_WINDOW", login_root.destroy)
        
        # 整体布局：左右 PanedWindow
        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief="raised")
        paned.pack(fill=tk.BOTH, expand=True)
        
        # --- 左侧：场馆列表 ---
        self.left_frame = tk.Frame(paned, width=650)
        paned.add(self.left_frame, stretch="always")
        
        # --- 右侧：任务列表 ---
        self.right_frame = tk.Frame(paned, width=350, bg="#f2f2f2")
        paned.add(self.right_frame, stretch="never")
        
        # 初始化左右 UI
        self._init_left_ui()
        self._init_right_ui()
        
        # 异步加载数据
        self.load_venues()
        self.refresh_task_list()

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
        
        # 任务列表容器 (Canvas + Scrollbar)
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

        # 底部刷新按钮
        btn_refresh = tk.Button(self.right_frame, text="刷新任务状态", command=self.refresh_task_list, bg="#ddd")
        btn_refresh.pack(pady=10, fill="x", padx=10)

    # --- 左侧逻辑 ---
    def load_venues(self):
        threading.Thread(target=self._thread_load_venues).start()

    def _thread_load_venues(self):
        success, html_content = api_handler.get_dashboard_html()
        if not success:
            self.after(0, lambda: self.loading_label.config(text=f"加载失败: {html_content}"))
            return
        
        # 解析 HTML
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
                    
                    # 使用名称作为 evaluate_name 的初始值
                    item_info = ItemInfo(name, item_type, name)
                    
                    img_bytes = None
                    if img_url:
                        img_bytes = api_handler.fetch_image_bytes(img_url)
                        
                    items_data.append({
                        "name": name,
                        "img_bytes": img_bytes,
                        "item_info": item_info
                    })
        
        self.after(0, lambda: self._render_venues(items_data))

    def _render_venues(self, items):
        self.loading_label.destroy()
        
        # 使用 Grid 布局绘制按钮
        cols = 3
        for i, item in enumerate(items):
            r, c = divmod(i, cols)
            
            # 点击事件：调用 show_venue_page (流程入口)
            # 传递 self (DashboardWindow) 以便它可以被隐藏
            cmd = lambda info=item["item_info"]: show_venue_page_flow(info, self)
            
            # 使用原生按钮 compound="top"
            btn = tk.Button(self.venue_container, 
                            text=item["name"], 
                            command=cmd,
                            font=("微软雅黑", 10, "bold"),
                            bg="white", 
                            relief="raised",
                            bd=2,
                            width=18, height=8) # 字符单位
            
            if item["img_bytes"]:
                try:
                    pil_img = Image.open(io.BytesIO(item["img_bytes"]))
                    pil_img = pil_img.resize((50, 50), Image.Resampling.LANCZOS)
                    tk_img = ImageTk.PhotoImage(pil_img)
                    image_references.append(tk_img) # 防止回收
                    
                    # 图片在上，设置像素大小
                    btn.config(image=tk_img, compound="top", width=140, height=100)
                except:
                    pass
            
            btn.grid(row=r, column=c, padx=15, pady=15)

    # --- 右侧逻辑 ---
    def refresh_task_list(self):
        """读取 JSON 并刷新右侧任务列表"""
        # 清空
        for w in self.task_list_frame.winfo_children():
            w.destroy()
        
        tasks = task_manager.load_tasks()
        
        if not tasks:
            tk.Label(self.task_list_frame, text="暂无抢票任务", bg="#f2f2f2", fg="#888").pack(pady=20)
            return

        for idx, task in enumerate(tasks):
            # 卡片容器
            card = tk.Frame(self.task_list_frame, bg="white", bd=1, relief="solid")
            card.pack(fill="x", padx=5, pady=5)
            
            # 左侧信息
            info_frame = tk.Frame(card, bg="white")
            info_frame.pack(side="left", padx=10, pady=5)
            
            tk.Label(info_frame, text=f"{task['date']}  {task['time']}", font=("Arial", 10, "bold"), bg="white", fg="#FF8C00").pack(anchor="w")
            tk.Label(info_frame, text=f"{task['venue_name']}", font=("Arial", 9), bg="white").pack(anchor="w")
            tk.Label(info_frame, text=f"区域: {task['area_name']}", font=("Arial", 9, "italic"), bg="white", fg="#666").pack(anchor="w")
            
            # 右侧取消按钮
            btn_del = tk.Button(card, text="取消", bg="#FF6347", fg="white", font=("Arial", 9), 
                                relief="flat", command=lambda i=idx: self._delete_task(i))
            btn_del.pack(side="right", padx=10, pady=10)

    def _delete_task(self, index):
        if messagebox.askyesno("确认", "确定要取消这个自动抢票任务吗？"):
            task_manager.delete_task(index)
            self.refresh_task_list()


# =============================================================================
#  加载流程控制 (加载配置 -> 获取默认数据 -> 打开选座窗口)
# =============================================================================

def show_venue_page_flow(item_info, dashboard_window):
    """
    流程入口：
    1. 隐藏主 Dashboard
    2. 显示临时 Loading 窗口
    3. 后台请求 Particulars 页面配置
    4. 后台请求 GetDayPlay 数据 (支持Mock)
    5. 关闭 Loading，打开 VenueSelectionWindow (Window A)
    """
    dashboard_window.withdraw()
    
    loading_win = tk.Toplevel()
    loading_win.title("连接中")
    loading_win.geometry("300x120")
    # 居中
    screen_width = loading_win.winfo_screenwidth()
    screen_height = loading_win.winfo_screenheight()
    x = (screen_width - 300) // 2
    y = (screen_height - 120) // 2
    loading_win.geometry(f"+{x}+{y}")
    
    tk.Label(loading_win, text=f"正在连接 {item_info.name}...", font=("微软雅黑", 11)).pack(pady=15)
    tk.Label(loading_win, text="获取未来7天排期中...", fg="#666").pack()

    # 启动后台线程
    threading.Thread(target=thread_process_data, 
                     args=(loading_win, dashboard_window, item_info)).start()

def thread_process_data(loading_win, dashboard_window, item_info):
    # 1. 获取 particualrs 页面配置 (日期和区域列表)
    success_opt, result_opt = api_handler.get_booking_options(item_info.item_type)
    
    if not success_opt:
        loading_win.after(0, lambda: [messagebox.showerror("错误", f"获取配置失败: {result_opt}"), 
                                      loading_win.destroy(), dashboard_window.deiconify()])
        return

    # 提取配置
    default_date = result_opt['default_date']
    default_area = result_opt['default_area']
    # 强制使用 API Handler 提供的未来7天生成器 (确保日期连续)
    all_dates = api_handler.get_next_7_days() 
    all_areas = result_opt['areas']
    
    # 2. 获取具体数据 (如果接口没数据，内部已做 mock)
    # 使用 all_dates[0] 即今天或明天作为默认请求日期
    target_date = all_dates[0]
    
    success_data, result_data = api_handler.get_venue_data(item_info.item_type, default_area, target_date)
    
    # 关闭 Loading
    loading_win.after(0, loading_win.destroy)
    
    if not success_data:
        # 虽然 api_handler 做了 mock，但如果是网络彻底断开等 error，这里处理
        loading_win.after(0, lambda: [messagebox.showerror("错误", f"加载数据异常: {result_data}"), 
                                      dashboard_window.deiconify()])
        return

    # 3. 打开大窗口
    loading_win.after(0, lambda: open_selection_window(
        dashboard_window, item_info, 
        default_area, target_date, 
        all_areas, all_dates, 
        result_data
    ))

def open_selection_window(dashboard_window, item_info, area, date, all_areas, all_dates, data):
    
    def on_save_tasks(selected_list):
        """点击【设置自动抢】后的回调"""
        if selected_list:
            task_manager.save_task(selected_list)
            # 这里不关闭窗口，而是让 VenueSelectionWindow 内部刷新显示状态
            pass

    # 实例化窗口 A
    VenueSelectionWindow(dashboard_window, item_info, area, date, 
                         all_areas, all_dates, data, on_save_tasks)


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
        # 恢复按钮
        root.after(0, lambda: login_button.config(text="登 录", state=tk.NORMAL))
        
        if success:
            # 登录成功，切换到主面板
            root.after(0, lambda: [root.withdraw(), DashboardWindow(root)])
        else:
            root.after(0, lambda: messagebox.showerror("登录失败", msg))
            
    threading.Thread(target=_login).start()


# =============================================================================
#  程序入口
# =============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    root.title("用户登录")
    root.geometry("350x200") 
    root.resizable(False, False) 
    
    # 居中显示
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

    root.mainloop()