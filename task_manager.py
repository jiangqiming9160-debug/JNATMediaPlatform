import json
import os
import threading

TASK_FILE = 'booking_tasks.json'
_lock = threading.Lock()

def load_tasks():
    """加载所有任务"""
    if not os.path.exists(TASK_FILE):
        return []
    try:
        with open(TASK_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_task(new_tasks):
    """保存新任务列表 (追加)"""
    with _lock:
        current_tasks = load_tasks()
        # 简单的去重逻辑 (根据日期、时间、场地名)
        for new_t in new_tasks:
            is_exist = False
            for old_t in current_tasks:
                if (old_t['date'] == new_t['date'] and 
                    old_t['time'] == new_t['time'] and 
                    old_t['venue_name'] == new_t['venue_name'] and 
                    old_t['area_name'] == new_t['area_name']):
                    is_exist = True
                    break
            if not is_exist:
                current_tasks.append(new_t)
        
        with open(TASK_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_tasks, f, indent=4, ensure_ascii=False)

def delete_task(task_index):
    """删除指定索引的任务"""
    with _lock:
        tasks = load_tasks()
        if 0 <= task_index < len(tasks):
            tasks.pop(task_index)
            with open(TASK_FILE, 'w', encoding='utf-8') as f:
                json.dump(tasks, f, indent=4, ensure_ascii=False)
            return True
        return False

def get_scheduled_cells(area_name, date_str):
    """
    获取指定区域和日期下，已经被设置为自动抢的时间点集合
    返回 set: {'08:00', '09:00'}
    """
    tasks = load_tasks()
    booked_times = set()
    for t in tasks:
        if t.get('area_name') == area_name and t.get('date') == date_str:
            booked_times.add(t.get('time'))
    return booked_times