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
import matplotlib.pyplot as plt

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
    index_code = "sh000002" 
    index_name = "上证A股"
    limit_ratio = 1.10
    
    if stock_code.startswith("6"):
        index_code = "sh000002" 
        index_name = "上证A股"
        if stock_code.startswith("688"):
            limit_ratio = 1.20
    elif stock_code.startswith("0") or stock_code.startswith("3"):
        index_code = "sz399107"
        index_name = "深证A股"
        if stock_code.startswith("300"):
            limit_ratio = 1.20 # 创业板
    
    # 北交所处理 (以8开头等) 简单兼容，或暂按上证处理
    if stock_code.startswith("8") or stock_code.startswith("4"):
         limit_ratio = 1.30 # 北交所30%
         index_code = "sh000002" # 暂时没有北交所特定指数的数据源，暂用上证代替

    return index_code, index_name, limit_ratio

def get_future_trading_dates(start_date_str, count):
    dates = []
    try:
        df = ak.tool_trade_date_hist_sina()
        all_dates = df['trade_date'].astype(str).tolist()
        dates = [d for d in all_dates if d > start_date_str]
        dates = dates[:count]
    except:
        pass
    
    try:
        current_date = datetime.strptime(start_date_str, "%Y%m%d")
    except:
        return [f"T+{i+1}" for i in range(count)]

    while len(dates) < count:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5:
            d_str = current_date.strftime("%Y%m%d")
            if d_str not in dates:
                dates.append(d_str)
    return dates

def analyze_period_combined(df, future_dates, days, threshold, limit_ratio):
    result_data = []
    current_idx = len(df) - 1
    
    # 确保有数据
    if current_idx < 0: return pd.DataFrame()

    t_row = df.iloc[current_idx]
    current_price = t_row['close']
    current_index = t_row['index_close']
    
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
            base_idx = target_idx - days
            p_prev = df.iloc[target_idx - 1]['close'] if target_idx > 0 else p_end
        else:
            type_label = "预测"
            date_str = future_dates[offset - 1]
            try:
                target_date_str = datetime.strptime(date_str, "%Y%m%d").strftime("%m-%d") + f"(T+{offset})"
            except:
                target_date_str = f"{date_str}(T+{offset})"
            
            p_end = current_price
            i_end = current_index
            p_prev = current_price 
            actual_pct = 0.0
            base_idx = current_idx + offset - days

        if base_idx < 0: continue

        base_row = df.iloc[base_idx]
        p_base = base_row['close']
        i_base = base_row['index_close']
        base_date_str = base_row['date']

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
            "基准日期": base_date_str,
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

try:
    plt.style.use('seaborn-v0_8-whitegrid')
except:
    plt.style.use('ggplot')

matplotlib.rcParams['font.family'] = ['Times New Roman', 'SimSun', 'SimHei']
matplotlib.rcParams['axes.unicode_minus'] = False

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

def plot_summary_overview(summary_data, title_prefix):
    if not summary_data: return

    meta_dates = ("T+1", "T+2", "T+3")
    if "_meta_dates" in summary_data[0]:
        meta_dates = summary_data[0]["_meta_dates"]
    
    clean_data = []
    for item in summary_data:
        new_item = item.copy()
        if "_meta_dates" in new_item: del new_item["_meta_dates"]
        clean_data.append([
            new_item['名称'], new_item['现价'], new_item['T_偏离'],
            new_item['T1_触线'], new_item['T1_空间'], new_item['T1_板'],
            new_item['T2_触线'], new_item['T2_空间'], new_item['T2_板'],
            new_item['T3_触线'], new_item['T3_空间'], new_item['T3_板']
        ])
    
    n_cols = 12 
    n_rows = len(clean_data)
    fig_width = TABLE_FIG_WIDTH
    fig_height = max(1.5, n_rows * TABLE_FIG_HEIGHT_PER_ROW + TABLE_FIG_HEIGHT_BASE)
    
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis('off')
    
    header_main_color = '#2c3e50'
    row_colors = ['#ffffff', '#f2f2f2']
    d1, d2, d3 = meta_dates
    headers = [
        "名称", "现价", "当前\n偏离", 
        f"{d1}\n触线价", f"{d1}\n允许涨幅", f"{d1}\n连板",
        f"{d2}\n触线价", f"{d2}\n允许涨幅", f"{d2}\n连板",
        f"{d3}\n触线价", f"{d3}\n允许涨幅", f"{d3}\n连板"
    ]
    
    full_table_data = [headers] + clean_data
    table = ax.table(cellText=full_table_data, cellLoc='center', loc='center', bbox=[0, 0, 1, 1])
    
    table.auto_set_font_size(False)
    table.set_fontsize(TABLE_CELL_FONT_SIZE_NORMAL)
    
    cells = table.get_celld()
    for (row, col), cell in cells.items():
        cell.set_linewidth(0.5)
        if row == 0:
            cell.set_facecolor(header_main_color)
            cell.set_text_props(weight='bold', color='white', size=TABLE_HEADER_FONT_SIZE)
            cell.set_height(TABLE_HEADER_HEIGHT)
        else:
            data_row_idx = row - 1
            cell.set_height(TABLE_ROW_HEIGHT)
            cell.set_facecolor(row_colors[data_row_idx % 2])
            text_val = cell.get_text().get_text()
            
            if col == 0: cell.set_text_props(weight='bold')
            if col == 2:
                try:
                    val = float(text_val.replace('%', ''))
                    rounded_val = round_half_up(val, 2)
                    cell.get_text().set_text(f"{rounded_val:.2f}") 
                    if abs(val) > 80: cell.set_text_props(color='red', weight='bold')
                except: pass
            if col in [4, 7, 10]:
                if "触发" in text_val or "已触发" in text_val:
                    cell.set_text_props(color='white', weight='bold')
                    cell.set_facecolor('#c0392b')
                else:
                    try:
                        val = float(text_val.replace('%', ''))
                        rounded_val = round_half_up(val, 2)
                        cell.get_text().set_text(f"{rounded_val:.2f}") 
                        if val < 10.0: cell.set_text_props(color='red', weight='bold')
                        elif val < 20.0: cell.set_text_props(color='#e67e22', weight='bold') 
                    except: pass
            if col in [5, 8, 11]:
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
        
        # 顶部输入区域
        top_frame = tk.Frame(root, pady=10)
        top_frame.pack(fill=tk.X, padx=10)
        
        tk.Label(top_frame, text="股票列表 (每行一个，格式：代码 名称):", font=("微软雅黑", 10)).pack(anchor="w")
        
        self.input_text = scrolledtext.ScrolledText(top_frame, height=6, font=("Consolas", 10))
        self.input_text.pack(fill=tk.X, pady=5)
        # 默认值
        default_stocks = """600372 中航机载
601698 中国卫通
600435 北方导航"""
        self.input_text.insert(tk.END, default_stocks)
        
        btn_frame = tk.Frame(top_frame)
        btn_frame.pack(fill=tk.X)
        
        self.run_btn = tk.Button(btn_frame, text="开始分析", command=self.start_analysis, bg="#007acc", fg="white", font=("微软雅黑", 10, "bold"), padx=20)
        self.run_btn.pack(side=tk.LEFT)
        
        self.save_img_var = tk.BooleanVar(value=True)
        tk.Checkbutton(btn_frame, text="同时保存图片到images目录", variable=self.save_img_var).pack(side=tk.LEFT, padx=20)

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
        self.run_btn.config(state='disabled', text="运行中...")
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

        # 启动线程
        threading.Thread(target=self.run_process, args=(stock_list,), daemon=True).start()

    def run_process(self, stock_list):
        summary_list_10 = []
        summary_list_30 = []
        
        target_date_str = datetime.now().strftime("%Y%m%d")
        self.log(f"分析日期: {target_date_str}")
        self.log(f"共 {len(stock_list)} 支股票待处理...")
        self.log("-" * 40)

        for code, name in stock_list:
            try:
                self.log(f"正在处理: {code} {name} ...")
                s10, s30 = self.process_one_stock(code, name, target_date_str)
                if s10: summary_list_10.append(s10)
                if s30: summary_list_30.append(s30)
                time.sleep(0.5) 
            except Exception as e:
                self.log(f"处理出错: {str(e)}")

        self.log("\n" + "="*40)
        self.log("分析完成。生成汇总表...")
        
        # 显示 10日异动汇总
        if summary_list_10:
            self.print_summary_table("10日严重异动 (100%偏离)", summary_list_10)
        
        if summary_list_30:
            self.print_summary_table("30日严重异动 (200%偏离)", summary_list_30)

        self.root.after(0, lambda: self.run_btn.config(state='normal', text="开始分析"))
        messagebox.showinfo("完成", "分析已完成！")

    def print_summary_table(self, title, summary_data):
        if not summary_data: return
        
        # 提取用于显示的列
        headers = ["名称", "现价", "T_偏离", "T1_板", "T1_空间", "T1_触线", "T2_板", "T2_空间", "T3_板", "T3_空间"]
        
        # 构建 DataFrame 以利用 pandas 的格式化
        rows = []
        for item in summary_data:
            row = [
                item['名称'], item['现价'], item['T_偏离'],
                item['T1_板'], item['T1_空间'], item['T1_触线'],
                item['T2_板'], item['T2_空间'],
                item['T3_板'], item['T3_空间']
            ]
            rows.append(row)
            
        df = pd.DataFrame(rows, columns=headers)
        
        table_str = df.to_string(index=False)
        
        self.log(f"\n【{title} 汇总表】")
        self.log(table_str)
        
        # 如果需要保存图片
        if self.save_img_var.get():
             try:
                 plot_summary_overview(summary_data, title.split(' ')[0])
             except Exception as e:
                 self.log(f"绘图失败: {e}")

    def process_one_stock(self, stock_code, name, target_date_str):
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
        future_dates = get_future_trading_dates(last_date_str, 3)

        df_10 = analyze_period_combined(merged, future_dates, 10, 100.0, limit_ratio)
        df_30 = analyze_period_combined(merged, future_dates, 30, 200.0, limit_ratio)

        def extract_summary(res_df):
            row_map = {}
            for idx, row in res_df.iterrows():
                if row['类型'] == '今日' or row['日期'] == last_date_str:
                    row_map['T'] = row
                elif '(T+1)' in row['日期']: row_map['T+1'] = row
                elif '(T+2)' in row['日期']: row_map['T+2'] = row
                elif '(T+3)' in row['日期']: row_map['T+3'] = row
            
            t_row = row_map.get('T', {})
            t1_row = row_map.get('T+1', {})
            t2_row = row_map.get('T+2', {})
            t3_row = row_map.get('T+3', {})

            def get_date_str(r_row, default_suffix=""):
                raw = r_row.get("日期", "")
                if not raw: return default_suffix
                if "(" in raw: return raw.split("(")[0]
                if len(raw) == 8 and raw.isdigit(): return f"{raw[4:6]}-{raw[6:8]}"
                return raw

            date_t1 = get_date_str(t1_row, "T+1")
            date_t2 = get_date_str(t2_row, "T+2")
            date_t3 = get_date_str(t3_row, "T+3")
            
            return {
                "_meta_dates": (date_t1, date_t2, date_t3),
                "名称": name,
                "现价": f"{current_price:.2f}",
                "T_偏离": t_row.get("区间偏离", "-"),
                "T1_触线": t1_row.get("触线价格", "-"),
                "T1_空间": t1_row.get("允许涨幅", "-"),
                "T1_板": t1_row.get("允许连板", "-"),
                "T2_触线": t2_row.get("触线价格", "-"),
                "T2_空间": t2_row.get("允许涨幅", "-"),
                "T2_板": t2_row.get("允许连板", "-"),
                "T3_触线": t3_row.get("触线价格", "-"),
                "T3_空间": t3_row.get("允许涨幅", "-"),
                "T3_板": t3_row.get("允许连板", "-"),
            }

        if self.save_img_var.get():
             safe_name = name.replace('*', '').replace(':', '')
             title_base = f"{safe_name}({stock_code})异动分析({last_date_str})"
             plot_result_table(df_10, f"{title_base}-10日(100%)")
             plot_result_table(df_30, f"{title_base}-30日(200%)")

        return extract_summary(df_10), extract_summary(df_30)

if __name__ == "__main__":
    if hasattr(sys, '_MEIPASS'):
        # 修正 pyinstaller 打包后的资源路径问题 (如果以后有静态文件)
        os.chdir(sys._MEIPASS)
        
    root = tk.Tk()
    app = AnalysisApp(root)
    root.mainloop()
