import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import sys
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
import time
import os
import matplotlib
matplotlib.use('Agg') # 强制使用非交互式后端，修复多线程报错
import matplotlib.pyplot as plt
import socket
socket.setdefaulttimeout(15) # 设置全局网络超时时间(秒)

DEFAUT_STOKE = """600372 中航机载
600435 北方导航
002519 银河电子
600783 鲁信创投
002151 北斗星通
002202 金风科技
600879 航天电子
600118 中国卫星
002792 通宇通讯
002131 利欧股份"""



DEFAUT_STOKE2 = """600372 中航机载
601698 中国卫通
600435 北方导航
002519 银河电子
000700 模塑科技
002361 神剑股份
002759 天际股份
603601 再升科技
600783 鲁信创投
002151 北斗星通
002565 顺灏股份
002202 金风科技
600879 航天电子
000559 万向钱潮
600118 中国卫星
002149 西部材料
000547 航天发展
002792 通宇通讯
002413 雷科防务
002131 利欧股份
002788 鹭燕医药
002625 光启技术
300058 蓝色光标
"""

# ================= 核心逻辑 (复用自原脚本) =================

def round_half_up(value, decimals=2):
    try:
        d = Decimal(str(value))
        fmt = "0." + "0" * decimals
        return float(d.quantize(Decimal(fmt), rounding=ROUND_HALF_UP))
    except:
        return value

def get_realtime_quote_single(code):
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=code, period='1', adjust='')
        if df is None or df.empty:
            return None
        last_row = df.iloc[-1]
        time_str = str(last_row['时间'])
        price = float(last_row['收盘'])
        return {'time': time_str, 'price': price}
    except Exception as e:
        return None

def get_market_rules(stock_code):
    # 默认值 (上交所主板)
    # 上证A股指数: 根据最新信息，使用 000002 或 999998 (wind/交易所代码习惯不同，akshare通常支持sh000002)
    # sh000002 是上证A股指数的标准代码
    index_code = "sh000002"
    index_name = "上证A股"
    limit_ratio = 1.10
    
    # 1. 科创板 (688开头)
    if stock_code.startswith("688"):
        # 核心基准: 科创50 (000688)
        index_code = "sh000688"
        index_name = "科创50"
        limit_ratio = 1.20

    # 2. 上交所主板 (60开头)
    elif stock_code.startswith("60"):
        # 基准: 上证A股 (000002)
        index_code = "sh000002" 
        index_name = "上证A股"
        limit_ratio = 1.10

    # 3. 创业板 (30开头)
    elif stock_code.startswith("30"):
        # 基准: 创业板综 (399102)
        index_code = "sz399102"
        index_name = "创业板综"
        limit_ratio = 1.20

    # 4. 深交所主板 (00开头)
    elif stock_code.startswith("00"):
        # 基准: 深证A股 (399107)
        index_code = "sz399107"
        index_name = "深证A股"
        limit_ratio = 1.10

    # 5. 北交所 (8开头)
    elif stock_code.startswith("8") or stock_code.startswith("92"): 
         # 基准: 北证50 (899050)
         # 尝试使用 sz899050 (AKShare部分接口可能支持)
         # 如果接口报错，需要后续维护
         index_code = "sz899050" 
         index_name = "北证50"
         limit_ratio = 1.30 

    return index_code, index_name, limit_ratio

def get_future_trading_dates(start_date_str, count):
    dates = []
    
    # 1. 优先尝试读取本地 trading_dates.txt
    # 文件格式: 每行一个日期 YYYYMMDD
    if os.path.exists("trading_dates.txt"):
        try:
            with open("trading_dates.txt", "r", encoding='utf-8') as f:
                # 读取并清洗数据
                file_dates = []
                for line in f:
                    d = line.strip()
                    if d.isdigit() and len(d) == 8:
                        file_dates.append(d)
                
                # 排序并筛选
                file_dates.sort()
                dates = [d for d in file_dates if d > start_date_str]
                if len(dates) >= count:
                    return dates[:count]
        except Exception as e:
            print(f"读取 trading_dates.txt 失败: {e}")

    # 2. 尝试从 AKShare 获取 (修正了日期格式转换)
    try:
        df = ak.tool_trade_date_hist_sina()
        # 强制转换为 YYYYMMDD 格式字符串
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')
        all_dates = df['trade_date'].tolist()
        
        ak_dates = [d for d in all_dates if d > start_date_str]
        if len(ak_dates) >= count:
            # 如果AKShare数据足够，直接使用
            # 只有当 AKShare 返回了有效未来日期时才覆盖
            dates = ak_dates[:count]
    except:
        pass
    
    # 如果已经获取到足够的日期，直接返回
    if len(dates) >= count:
        return dates[:count]

    # 3. 兜底回退逻辑 (仅排除周末，不包含节假日)
    # 如果 dates 有部分数据(比如来自本地文件但不够)，则基于最后一个日期继续推算
    if dates:
        try:
            current_date = datetime.strptime(dates[-1], "%Y%m%d")
        except:
            current_date = datetime.strptime(start_date_str, "%Y%m%d")
    else:
        try:
            current_date = datetime.strptime(start_date_str, "%Y%m%d")
        except:
            return [f"T+{i+1}" for i in range(count)]

    # 补齐剩余所需的日期
    while len(dates) < count:
        current_date += timedelta(days=1)
        # 0-4 是周一到周五
        if current_date.weekday() < 5:
            d_str = current_date.strftime("%Y%m%d")
            # 避免重复添加
            if d_str not in dates:
                dates.append(d_str)
                
    return dates

def analyze_period_combined(df, future_dates, days, threshold, limit_ratio, strict_mode=False):
    result_data = []
    current_idx = len(df) - 1
    
    # 确保有数据
    if current_idx < 0: return pd.DataFrame()

    t_row = df.iloc[current_idx]
    current_price = t_row['close']
    current_index = t_row['index_close']
    
    # 预计算：为了严格模式，我们需要快速访问历史价格
    # df 已经包含直到 current_idx 的历史数据
    # 对于未来预测日，价格假设为 current_price
    
    for offset in range(-2, len(future_dates) + 1):
        if offset <= 0:
            type_label = "历史" if offset < 0 else "今日"
            target_idx = current_idx + offset
            if target_idx < 0: continue
            
            target_row = df.iloc[target_idx]
            target_date_str = target_row['date']
            p_end = target_row['close']
            i_end = target_row['index_close']
            actual_pct = target_row['pct_chg']
            
            # 标准基准
            base_idx = target_idx - days
            p_prev = df.iloc[target_idx - 1]['close'] if target_idx > 0 else p_end
        else:
            type_label = "预测"
            date_str = future_dates[offset - 1]
            try:
                target_date_str = datetime.strptime(date_str, "%Y%m%d").strftime("%m-%d") + f"(T+{offset})"
            except:
                target_date_str = f"{date_str}(T+{offset})"
            
            p_end = current_price # 假设未来价格不变
            i_end = current_index
            p_prev = current_price 
            actual_pct = 0.0
            
            # 标准基准索引 (相对于df)
            target_idx = current_idx + offset
            base_idx = target_idx - days 

        if base_idx < 0: continue

        # --- 获取基准数据 (Standard vs Strict) ---
        if strict_mode:
            # 严格模式：寻找 [target_idx - days, target_idx] 区间内的最低价作为基准
            # 注意：区间可能包含“未来日”，未来日价格 = current_price
            
            # 1. 确定搜索范围在 df 中的有效部分
            # search_start_idx = base_idx
            # search_end_idx = target_idx (inclusive)
            
            min_price = 999999.0
            best_base_row = None
            
            # 遍历寻找最低点
            # 实际上主要是历史部分有波动，未来部分是平的(current_price)
            # 所以只有当 current_price < historical_min 时，未来部分才会成为基准(一般不出现，除非暴跌)
            # 我们主要搜索历史部分 [base_idx, min(target_idx, current_idx)]
            
            search_end_real = min(target_idx, current_idx)
            
            # 优化：仅在历史范围内搜索
            if search_end_real >= base_idx:
                # 切片搜索
                subset = df.iloc[base_idx : search_end_real + 1]
                if not subset.empty:
                    min_idx_relative = subset['close'].idxmin()
                    min_price = subset.loc[min_idx_relative, 'close']
                    best_base_row = subset.loc[min_idx_relative]
            
            # 如果区间包含未来部分，且当前价格比历史最低还低（极少见），则更新
            if target_idx > current_idx:
                if current_price < min_price:
                    min_price = current_price
                    # 虚拟 row
                    best_base_row = {'close': current_price, 'index_close': current_index, 'date': 'Future'}
            
            if best_base_row is None:
                 base_row = df.iloc[base_idx] # Fallback
            else:
                 base_row = best_base_row
                 
        else:
            # 标准模式：严格 T-30
            # 如果 base_idx > current_idx (未来)，由于我们假设指数不变，取 current
            if base_idx > current_idx:
                base_row = {'close': current_price, 'index_close': current_index, 'date': 'Future(Base)'}
            else:
                base_row = df.iloc[base_idx]

        p_base = base_row['close']
        i_base = base_row['index_close']
        base_date_str = base_row.get('date', 'Unknown')

        try:
            d_p_end = Decimal(str(p_end)) 
            d_p_base = Decimal(str(p_base))
            d_i_end = Decimal(str(i_end))
            d_i_base = Decimal(str(i_base))
            
            stock_cum_d = ((d_p_end / d_p_base) - 1) * 100
            index_cum_d = ((d_i_end / d_i_base) - 1) * 100
            
            deviation_d = stock_cum_d - index_cum_d
            
            stock_cum = float(stock_cum_d)
            index_cum = float(index_cum_d)
            deviation = float(deviation_d)
        except:
            stock_cum = (p_end / p_base - 1) * 100
            index_cum = (i_end / i_base - 1) * 100
            deviation = stock_cum - index_cum
        
        is_triggered = abs(deviation) >= threshold
        
        target_stock_cum = threshold + index_cum
        trigger_price = p_base * (1 + target_stock_cum / 100)
        
        left_space = threshold - deviation
        
        rp_tri_pri = round_half_up(trigger_price, 2)
        room_pct = (rp_tri_pri / p_prev - 1) * 100 if p_prev > 0 else 0
            
        limit_boards_val = 0
        if room_pct > 0:
             ratio = 1 + room_pct/100
             if ratio > 1 and math.log(limit_ratio) > 0:
                limit_boards_val = math.floor(math.log(ratio) / math.log(limit_ratio))
        
        row_dict = {
            "日期": target_date_str,
            "类型": type_label,
            "基准日期": base_date_str + ("(Low)" if strict_mode and base_date_str != "Future" else ""),
            "实际涨幅": f"{round_half_up(actual_pct, 2):.2f}%", 
            "区间偏离": f"{round_half_up(deviation, 2):.2f}%",
            "剩余空间": "已触发" if is_triggered else f"{round_half_up(left_space, 2):.2f}%",
            "触线价格": float(f"{round_half_up(trigger_price, 2):.2f}"),
            "允许涨幅": "0.00%" if is_triggered else f"{room_pct:.2f}%",
            "允许连板": 0 if is_triggered else limit_boards_val
        }
        result_data.append(row_dict)
    
    return pd.DataFrame(result_data)

# ================= 绘图逻辑 =================
import matplotlib
import matplotlib.font_manager as fm

def configure_plot_style():
    try:
        plt.style.use('seaborn-v0_8-whitegrid')
    except:
        plt.style.use('ggplot')

    # 自动探测系统支持的中文字体
    # 优先级: 微软雅黑 > 黑体 > 宋体 > 其他平台常见字体
    candidate_fonts = [
        'SimSun', 'SimHei','Microsoft YaHei', 'KaiTi',  # Windows
        'PingFang SC', 'Heiti TC', 'Hiragino Sans GB', 'Arial Unicode MS',  # Mac
        'WenQuanYi Micro Hei', 'Droid Sans Fallback', 'Noto Sans CJK SC'  # Linux
    ]
    
    # 获取系统所有可用字体名称集合
    try:
        system_font_names = set([f.name for f in fm.fontManager.ttflist])
    except:
        system_font_names = set()
    
    # 筛选出系统中存在的字体
    found_fonts = []
    for f in candidate_fonts:
        if f in system_font_names:
            found_fonts.append(f)
            
    # 默认回退列表 (即使检测不到也加上，作为最后防线)
    fallback_fonts = ['SimHei', 'SimSun', 'Microsoft YaHei']
    
    # 最终字体列表：优先 Times New Roman (英文/数字)，然后是检测到的可用中文字体
    # Matplotlib 会依次尝试列表中的字体来渲染字符
    final_font_family = ['Times New Roman'] + found_fonts + fallback_fonts
    
    matplotlib.rcParams['font.family'] = final_font_family
    matplotlib.rcParams['axes.unicode_minus'] = False

configure_plot_style()

# ================= 表格绘图超参数 =================
TABLE_TITLE_FONT_SIZE = 24
TABLE_HEADER_FONT_SIZE = 13
TABLE_CELL_FONT_SIZE = 16
TABLE_CELL_FONT_SIZE_NORMAL = 14
TABLE_FIG_WIDTH = 12
TABLE_ROW_HEIGHT = 0.04
TABLE_HEADER_HEIGHT = 0.05
TABLE_FIG_HEIGHT_BASE = 1.0
TABLE_FIG_HEIGHT_PER_ROW = 0.4

def plot_summary_overview(summary_data, title_prefix, show_boards=True):
    if not summary_data: return

    meta_dates = []
    if "_meta_dates" in summary_data[0]:
        meta_dates = summary_data[0]["_meta_dates"]
    
    clean_data = []
    # 动态构建列：名称, 现价, T1组...
    
    for item in summary_data:
        new_item = item.copy()
        if "_meta_dates" in new_item: del new_item["_meta_dates"]
        
        row_data = [
            new_item.get('名称', '-'),
            new_item.get('现价', '-')
        ]
        
        # 根据 meta_dates 的长度确定有多少天的数据
        for i in range(1, len(meta_dates) + 1):
            row_data.append(new_item.get(f'T{i}_触线', '-'))
            row_data.append(new_item.get(f'T{i}_空间', '-'))
            if show_boards:
                row_data.append(new_item.get(f'T{i}_板', '-'))
            
        clean_data.append(row_data)
    
    # 基础列 2 + 每天 (2 or 3) 列
    days_count = len(meta_dates)
    col_per_day = 3 if show_boards else 2
    n_cols = 2 + days_count * col_per_day
    n_rows = len(clean_data)
    
    # 动态计算宽度，基础宽度加上每天的增量
    width_per_day = 2.5 if show_boards else 1.8
    calc_width = 3 + days_count * width_per_day
    fig_width = max(TABLE_FIG_WIDTH, calc_width)
    fig_height = max(1.5, n_rows * TABLE_FIG_HEIGHT_PER_ROW + TABLE_FIG_HEIGHT_BASE)
    
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis('off')
    
    header_main_color = '#2c3e50'
    # 行背景色（保留淡灰斑马纹，但会被列背景色覆盖或混合？这里我们优先使用列背景色策略来区分天数）
    # 为了视觉清晰，我们将采用：行依然有斑马纹，但天数分组通过“边框”或者“微调背景色”？
    # 用户要求“浅色背景区分不同的天数”，最好的方式是 奇数天用浅色，偶数天用白色（叠加在行颜色上可能复杂）。
    # 简单方案：放弃行斑马纹，使用列组斑马纹。或者：列组颜色为主，行斑马纹调整亮度。
    
    # 采用方案：基础列白色，T1浅蓝，T2白色，T3浅蓝... (列纹)
    # 并在行方向保持轻微的深浅变化（行纹）
    
    basic_col_bg = '#ffffff'
    odd_day_bg = '#d4e6f1' # 加深：明显的浅蓝 (用于区分奇数天 T1, T3...)
    even_day_bg = '#ffffff' # 白 (用于偶数天 T2, T4...)
    
    headers = ["名称", "现价"]
    for i, d_str in enumerate(meta_dates):
        # 如果 d_str 太长 (比如 T+10)，只显示日期部分
        headers.append(f"{d_str}\n触线价")
        headers.append(f"{d_str}\n允许涨幅")
        if show_boards:
            headers.append(f"{d_str}\n连板")
    
    full_table_data = [headers] + clean_data
    table = ax.table(cellText=full_table_data, cellLoc='center', loc='center', bbox=[0, 0, 1, 1])
    
    table.auto_set_font_size(False)
    table.set_fontsize(TABLE_CELL_FONT_SIZE_NORMAL)
    
    cells = table.get_celld()
    for (row, col), cell in cells.items():
        cell.set_linewidth(0.5)
        # 默认背景色
        cell_bg = basic_col_bg
        
        # 计算列所属的分组
        # 0, 1: 基础组
        # 2, 3, [4]: T1 (Day 1)
        # ...
        day_idx = -1
        if col > 1:
            day_idx = (col - 2) // col_per_day # 0 for T1, 1 for T2 ...
            
        if day_idx >= 0:
            if (day_idx + 1) % 2 == 1: # 奇数天 (T1, T3...)
                cell_bg = odd_day_bg
            else:
                cell_bg = even_day_bg
        
        # 叠加行斑马纹 (让偶数行稍微暗一点点，增加可读性)
        if row > 0 and row % 2 == 0:
            # 加深斑马纹对比度
            if cell_bg == '#ffffff': cell_bg = '#eeeeee' # 加深的灰
            if cell_bg == odd_day_bg: cell_bg = '#c2dfee' # 加深的蓝

        if row == 0:
            cell.set_facecolor(header_main_color)
            cell.set_text_props(weight='bold', color='white', size=TABLE_HEADER_FONT_SIZE)
            cell.set_height(TABLE_HEADER_HEIGHT)
        else:
            data_row_idx = row - 1
            cell.set_height(TABLE_ROW_HEIGHT)
            cell.set_facecolor(cell_bg) # 应用背景色
            text_val = cell.get_text().get_text()
            
            # col 0: 名称
            if col == 0: cell.set_text_props(weight='bold')
            
            # 判断每一组 (触线, 涨幅, 连板) 中的 允许涨幅 列
            # 基础列索引是 0, 1
            if col > 1:
                rel_col = (col - 2) % col_per_day
                
                # 允许涨幅列
                if rel_col == 1:
                    if "触发" in text_val or "已触发" in text_val:
                        cell.set_text_props(color='white', weight='bold')
                        cell.set_facecolor('#c0392b')
                    else:
                        try:
                            val = float(text_val.replace('%', ''))
                            rounded_val = round_half_up(val, 2)
                            cell.get_text().set_text(f"{rounded_val:.2f}%") 
                            if val < 10.0: cell.set_text_props(color='red', weight='bold')
                            elif val < 20.0: cell.set_text_props(color='#e67e22', weight='bold') 
                            elif val < 30.0: cell.set_text_props(color='#2980b9', weight='bold') # 20-30% 蓝色提示
                        except: pass
                
                # 允许连板列
                if show_boards and rel_col == 2:
                    try:
                        val = int(text_val)
                        if val > 0:
                            cell.set_text_props(weight='bold', color='#2980b9')
                            cell.set_fontsize(TABLE_CELL_FONT_SIZE)
                    except: pass

    full_title = f"{title_prefix} - 异动分析总览"
    plt.title(full_title, fontsize=TABLE_TITLE_FONT_SIZE, weight='bold', pad=20)
    note_text = "备注: 未来三天允许最大涨幅基于 [假设当日股价不变(0%)且指数不变(0%)] 推算得出，仅供参考。"
    plt.figtext(0.5, 0.01, note_text, ha="center", fontsize=12, color="#555555")
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    
    if not os.path.exists("images"): os.makedirs("images")
    safe_title = f"images/总览_{title_prefix}_{datetime.now().strftime('%H%M')}.png"
    try:
        plt.savefig(safe_title, dpi=300, bbox_inches='tight')
    except: pass
    plt.close()

def plot_result_table(df, title):
    if df.empty: return
    rows, cols = df.shape
    fig_height = max(3, rows * 0.4 + 1.5)
    fig_width = 10 
    
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis('off')
    
    header_color = '#40466e'
    row_colors = ['#f9f9f9', '#ffffff'] 
    border_color = '#dddddd'

    table = ax.table(cellText=df.values, colLabels=df.columns, cellLoc='center', loc='center', bbox=[0, 0, 1, 1])

    table.auto_set_font_size(False)
    table.set_fontsize(16)
    
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor(border_color)
        cell.set_linewidth(1)
        
        if row == 0:
            cell.set_facecolor(header_color)
            cell.set_text_props(weight='bold', color='white', size=18)
            cell.set_height(0.12)
        else:
            cell.set_height(0.1)
            cell.set_facecolor(row_colors[row % 2])
            text_val = cell.get_text().get_text()
            column_name = df.columns[col]

            if column_name == "类型":
                if "预测" in text_val: cell.set_text_props(color='#d62728', weight='bold') 
                elif "今日" in text_val: cell.set_text_props(color='#2ca02c', weight='bold') 
                elif "历史" in text_val: cell.set_text_props(color='#7f7f7f')

            if column_name == "剩余空间":
                if "触发" in text_val or "已触发" in text_val:
                    cell.set_text_props(color='red', weight='bold')
                    cell.set_facecolor('#ffeeee')

            if column_name == "允许涨幅":
                try:
                    val_float = float(text_val.replace('%', ''))
                    if val_float < 10.0: cell.set_text_props(color='red', weight='bold') 
                    elif val_float < 20.0: cell.set_text_props(color='#e67e22', weight='bold')
                    elif val_float < 30.0: cell.set_text_props(color='#2980b9', weight='bold')
                except: pass

            if column_name == "允许连板":
                try:
                    val = int(text_val)
                    if val > 0: cell.set_text_props(weight='bold', color='#1f77b4')
                except: pass

    plt.title(title, fontsize=24, weight='bold', pad=20)
    plt.tight_layout()
    if not os.path.exists("images"): os.makedirs("images")
    filename = f"images/{title.replace(' ', '_').replace('/', '-')}.png"
    try:
        plt.savefig(filename, dpi=300, bbox_inches='tight')
    except: pass
    plt.close()

# ================= 界面逻辑 =================

class AnalysisApp:
    def __init__(self, root):
        self.root = root
        self.root.title("异动分析计算器 v1.0")
        self.root.geometry("1000x700")
        
        # 运行状态标志
        self.is_running = False
        self.stop_requested = False
        
        # 顶部输入区域
        top_frame = tk.Frame(root, pady=10)
        top_frame.pack(fill=tk.X, padx=10)
        
        tk.Label(top_frame, text="股票列表 (每行一个，格式：代码 名称):", font=("微软雅黑", 10)).pack(anchor="w")
        
        self.input_text = scrolledtext.ScrolledText(top_frame, height=6, font=("Consolas", 10))
        self.input_text.pack(fill=tk.X, pady=5)
        # 默认值
        default_stocks = DEFAUT_STOKE
        self.input_text.insert(tk.END, default_stocks)
        
        # 选项区域
        opt_frame = tk.Frame(top_frame)
        opt_frame.pack(fill=tk.X, pady=5)

        tk.Label(opt_frame, text="预测天数:").pack(side=tk.LEFT)
        self.days_entry = tk.Entry(opt_frame, width=5)
        self.days_entry.insert(0, "3")
        self.days_entry.pack(side=tk.LEFT, padx=5)
        tk.Label(opt_frame, text="(最大建议10天)").pack(side=tk.LEFT)

        self.save_img_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_frame, text="保存图片", variable=self.save_img_var).pack(side=tk.LEFT, padx=10)
        
        self.show_boards_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_frame, text="显示连板", variable=self.show_boards_var).pack(side=tk.LEFT, padx=5)

        self.strict_mode_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opt_frame, text="严格模式(区间最低点)", variable=self.strict_mode_var).pack(side=tk.LEFT, padx=5)

        btn_frame = tk.Frame(top_frame)
        btn_frame.pack(fill=tk.X)
        
        self.run_btn = tk.Button(btn_frame, text="开始分析", command=self.start_analysis, bg="#007acc", fg="white", font=("微软雅黑", 10, "bold"), padx=20)
        self.run_btn.pack(side=tk.LEFT)
        
        # 底部输出区域
        tk.Label(root, text="运行日志与结果:", font=("微软雅黑", 10)).pack(anchor="w", padx=10)
        
        self.output_text = scrolledtext.ScrolledText(root, height=20, font=("Consolas", 10), state='disabled')
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
    def log(self, msg):
        self.output_text.config(state='normal')
        self.output_text.insert(tk.END, msg + "\n")
        self.output_text.see(tk.END)
        self.output_text.config(state='disabled')
        self.root.update()

    def start_analysis(self):
        # 如果正在运行，则视为停止请求
        if self.is_running:
            if not self.stop_requested:
                 self.stop_requested = True
                 self.run_btn.config(text="正在中止...", state='disabled')
                 self.log("\n>>> 用户请求中止...")
            return

        self.output_text.config(state='normal')
        self.output_text.delete(1.0, tk.END)
        self.output_text.config(state='disabled')
        
        # 获取输入
        raw_input = self.input_text.get("1.0", tk.END).strip()
        lines = [l.strip() for l in raw_input.split('\n') if l.strip()]
        
        stock_list = []
        for line in lines:
            parts = line.replace(',', ' ').split()
            if len(parts) >= 1:
                code = parts[0]
                name = parts[1] if len(parts) > 1 else code
                stock_list.append((code, name))
        
        if not stock_list:
            messagebox.showwarning("提示", "请输入股票代码")
            self.run_btn.config(state='normal', text="开始分析")
            return

        # 获取预测天数
        try:
            days_count = int(self.days_entry.get().strip())
            if days_count <= 0: days_count = 3
            if days_count > 20: days_count = 20 # 限制一个硬上限防止卡死
        except:
            days_count = 3
        
        # 获取显示连板状态
        show_boards = self.show_boards_var.get()
        # 获取严格模式状态
        strict_mode = self.strict_mode_var.get()

        # 设置运行状态
        self.is_running = True
        self.stop_requested = False
        # 按钮变为红色停止按钮
        self.run_btn.config(state='normal', text="停止 / 刷新", bg="#e74c3c")

        # 启动线程
        threading.Thread(target=self.run_process, args=(stock_list, days_count, show_boards, strict_mode), daemon=True).start()

    def run_process(self, stock_list, days_count=3, show_boards=True, strict_mode=False):
        summary_list_10 = []
        summary_list_30 = []
        summary_list_combined = [] # 综合最严异动列表

        target_date_str = datetime.now().strftime("%Y%m%d")
        self.log(f"分析日期: {target_date_str}")
        self.log(f"预测天数: {days_count} 天")
        if strict_mode:
            self.log(f"模式: 严格模式 (基准 = 区间最低价)")
        else:
            self.log(f"模式: 标准模式 (基准 = T-N日收盘价)")
            
        self.log(f"共 {len(stock_list)} 支股票待处理...")
        self.log("-" * 40)

        def parse_space(val_str):
            # 解析剩余空间，返回float用于比较
            # "已触发" -> -9999 (优先级最高，最严)
            if not val_str: return 9999.0
            s_val = str(val_str)
            if "触发" in s_val: return -9999.0
            try:
                return float(s_val.replace('%', ''))
            except:
                return 9999.0

        for code, name in stock_list:
            # 检查中止标志
            if self.stop_requested:
                self.log(f"\n>>> 检测到中止信号，停止后续任务。")
                break

            try:
                self.log(f"正在处理: {code} {name} ...")
                s10, s30 = self.process_one_stock(code, name, target_date_str, days_count, strict_mode)
                
                # 收集分表数据
                if s10: summary_list_10.append(s10)
                if s30: summary_list_30.append(s30)

                # 计算综合极小值 (取T+1空间较小者)
                if s10 and s30:
                    v10 = parse_space(s10.get('T1_空间'))
                    v30 = parse_space(s30.get('T1_空间'))
                    if v10 <= v30:
                        summary_list_combined.append(s10)
                    else:
                        summary_list_combined.append(s30)
                elif s10:
                    summary_list_combined.append(s10)
                elif s30:
                    summary_list_combined.append(s30)

                time.sleep(0.5) 
            except socket.timeout:
                self.log(f"❌ 处理出错: 网络连接超时，请检查网络或重试。")
            except Exception as e:
                err_msg = str(e)
                if "timed out" in err_msg.lower():
                     err_msg = "网络请求超时"
                self.log(f"❌ 处理出错: {err_msg}")

        if not self.stop_requested:
            self.log("\n" + "="*40)
            self.log("分析完成。生成汇总表...")
            
            # 1. 显示 10日异动汇总
            if summary_list_10:
                self.print_summary_table("10日严重异动(100%偏离)", summary_list_10, show_boards=show_boards)
            
            # 2. 显示 30日异动汇总
            if summary_list_30:
                self.print_summary_table("30日严重异动(200%偏离)", summary_list_30, show_boards=show_boards)

            # 3. 显示 综合最严异动汇总 (仅显示这一张)
            if summary_list_combined:
                self.print_summary_table("异动分析总览(取T1空间极小值)", summary_list_combined, show_boards=show_boards)
            else:
                self.log("未生成任何有效异动数据。")

            messagebox.showinfo("完成", "分析已完成！")
        else:
             self.log("\n>>> 任务已手动中止。")

        self.is_running = False
        self.stop_requested = False
        self.root.after(0, lambda: self.run_btn.config(state='normal', text="开始分析", bg="#007acc"))

    def print_summary_table(self, title, summary_data, show_boards=True):
        if not summary_data: return
        
        # 探测数据中包含多少天 (读取一条数据看看T1, T2最大到多少)
        # 或者直接取 _meta_dates
        meta_dates = []
        if "_meta_dates" in summary_data[0]:
            meta_dates = summary_data[0]["_meta_dates"]
        
        if not meta_dates:
             # 兜底旧逻辑
             meta_dates = ["T+1", "T+2", "T+3"]

        # 动态构建列头
        headers = ["名称", "现价"]
        for i, _ in enumerate(meta_dates):
            idx = i + 1
            headers.extend([f"T{idx}_触线", f"T{idx}_空间"])
            if show_boards:
                headers.append(f"T{idx}_板")

        # 构建 DataFrame
        rows = []
        for item in summary_data:
            row = [
                item.get('名称', '-'), item.get('现价', '-')
            ]
            for i, _ in enumerate(meta_dates):
                idx = i + 1
                row.append(item.get(f"T{idx}_触线", '-'))
                row.append(item.get(f"T{idx}_空间", '-'))
                if show_boards:
                    row.append(item.get(f"T{idx}_板", '-'))
            rows.append(row)
            
        df = pd.DataFrame(rows, columns=headers)
        
        table_str = df.to_string(index=False)
        
        self.log(f"\n【{title} 汇总表】")
        self.log(table_str)
        
        # 如果需要保存图片
        if self.save_img_var.get():
             try:
                 plot_summary_overview(summary_data, title.split(' ')[0], show_boards=show_boards)
             except Exception as e:
                 import traceback
                 self.log(f"绘图失败: {e}")
                 traceback.print_exc()

    def process_one_stock(self, stock_code, name, target_date_str, days_count=3, strict_mode=False):
        index_code, index_name, limit_ratio = get_market_rules(stock_code)
        start_date = (pd.to_datetime(target_date_str) - timedelta(days=120)).strftime("%Y%m%d")
        
        # 1. 获取个股
        stock_df = ak.stock_zh_a_hist(symbol=stock_code, start_date=start_date, end_date=target_date_str, adjust="")
        
        # 补全实时数据
        need_realtime = False
        if stock_df is None or stock_df.empty:
             stock_df = pd.DataFrame(columns=['日期', '收盘', '涨跌幅'])
             need_realtime = True
        else:
             last_date = stock_df.iloc[-1]['日期']
             if isinstance(last_date, str):
                 last_d_str = last_date.replace('-', '')
             else:
                 last_d_str = last_date.strftime("%Y%m%d")
             if last_d_str < target_date_str:
                 need_realtime = True

        if need_realtime:
            real_data = get_realtime_quote_single(stock_code)
            if real_data:
                rt_time = real_data['time']
                rt_date_str = rt_time.split(' ')[0].replace('-', '')
                if rt_date_str > str(stock_df.iloc[-1]['日期'] if not stock_df.empty else '19900101').replace('-', ''):
                    price = real_data['price']
                    pct_chg = 0.0
                    if not stock_df.empty:
                         last_close = float(stock_df.iloc[-1]['收盘'])
                         if last_close > 0:
                            pct_chg = (price - last_close) / last_close * 100
                    
                    new_row = pd.DataFrame({'日期': [rt_date_str], '收盘': [float(price)], '涨跌幅': [float(pct_chg)]})
                    stock_df = pd.concat([stock_df, new_row], ignore_index=True)
                    self.log(f"   [实时补充] 现价:{price}")

        if stock_df is None or stock_df.empty:
            return None, None

        stock_df = stock_df.rename(columns={'日期': 'date', '收盘': 'close', '涨跌幅': 'pct_chg'})
        stock_df['date'] = pd.to_datetime(stock_df['date']).dt.strftime('%Y%m%d')

        # 2. 获取指数
        index_df = ak.stock_zh_index_daily(symbol=index_code)
        if index_df is None or index_df.empty:
            return None, None
            
        index_df['date'] = pd.to_datetime(index_df['date']).dt.strftime('%Y%m%d')
        index_df = index_df.sort_values('date')
        index_df['index_pct_chg'] = index_df['close'].pct_change() * 100 
        index_df = index_df.rename(columns={'close': 'index_close'})[['date', 'index_close', 'index_pct_chg']]
        
        merged = pd.merge(stock_df, index_df, on='date', how='left')
        if merged['index_close'].isnull().any():
            merged['index_close'] = merged['index_close'].ffill()
            merged['index_pct_chg'] = merged['index_pct_chg'].fillna(0.0)

        merged = merged.sort_values('date')
        merged = merged[merged['date'] <= target_date_str]
        
        if len(merged) < 30:
            self.log("   [警告] 数据不足30天")
            return None, None

        last_date_str = merged.iloc[-1]['date']
        current_price = merged.iloc[-1]['close']
        future_dates = get_future_trading_dates(last_date_str, days_count)

        df_10 = analyze_period_combined(merged, future_dates, 10, 100.0, limit_ratio, strict_mode)
        df_30 = analyze_period_combined(merged, future_dates, 30, 200.0, limit_ratio, strict_mode)

        def extract_summary(res_df, type_name):
            # 将所有预测行整理到字典 map
            row_map = {}
            for idx, row in res_df.iterrows():
                # T日（今天）
                if row['类型'] == '今日' or row['日期'] == last_date_str:
                    row_map['T'] = row
                else:
                    # 预测日 T+x
                    d_val = row['日期']
                    if "(T+" in d_val:
                        # 提取 T+x 部分
                        key = d_val.split("(")[1].replace(")", "") # T+1
                        row_map[key] = row
            
            t_row = row_map.get('T', {})
            
            # 动态生成结果
            summary_dict = {
                "名称": name,
                "异动类型": type_name,
                "现价": f"{current_price:.2f}",
                # "T_偏离": t_row.get("区间偏离", "-") # 已从总览移除
            }
            
            meta_dates_list = []
            
            # 根据 days_count 循环提取
            for i in range(1, days_count + 1):
                key = f"T+{i}"
                sub_row = row_map.get(key, {})
                
                # 获取日期显示字符串
                raw_d = sub_row.get("日期", "")
                if not raw_d: 
                     d_show_str = key
                else:
                    if "(" in raw_d: 
                        d_show_str = raw_d.split("(")[0] # 01-12
                    elif len(raw_d) == 8 and raw_d.isdigit(): 
                        d_show_str = f"{raw_d[4:6]}-{raw_d[6:8]}"
                    else:
                        d_show_str = raw_d
                
                meta_dates_list.append(d_show_str)
                
                # 设置 T1_xxx 字段
                summary_dict[f"T{i}_触线"] = sub_row.get("触线价格", "-")
                summary_dict[f"T{i}_空间"] = sub_row.get("允许涨幅", "-")
                summary_dict[f"T{i}_板"] = sub_row.get("允许连板", "-")

            summary_dict["_meta_dates"] = meta_dates_list
            return summary_dict

        if self.save_img_var.get():
             safe_name = name.replace('*', '').replace(':', '')
             title_base = f"{safe_name}({stock_code})异动分析({last_date_str})"
             plot_result_table(df_10, f"{title_base}-10日(100%)")
             plot_result_table(df_30, f"{title_base}-30日(200%)")

        return extract_summary(df_10, "10日"), extract_summary(df_30, "30日")

if __name__ == "__main__":
    if hasattr(sys, '_MEIPASS'):
        # 修正 pyinstaller 打包后的资源路径问题 (如果以后有静态文件)
        os.chdir(sys._MEIPASS)
        
    root = tk.Tk()
    app = AnalysisApp(root)
    root.mainloop()
