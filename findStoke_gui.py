import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import akshare as ak
import pandas as pd
import threading
from datetime import datetime
import os

class FindStockApp:
    def __init__(self, root):
        self.root = root
        self.root.title("最高价反查工具")
        self.root.geometry("700x500")
        
        # 缓存设置
        self.cached_df = None
        self.cache_time_str = None
        
        # 输入区域
        input_frame = tk.Frame(root, pady=10)
        input_frame.pack(fill=tk.X, padx=10)
        
        tk.Label(input_frame, text="输入当日最高价:").pack(side=tk.LEFT)
        self.price_entry = tk.Entry(input_frame, width=15)
        self.price_entry.pack(side=tk.LEFT, padx=5)
        self.price_entry.bind('<Return>', lambda event: self.start_search())
        
        self.search_btn = tk.Button(input_frame, text="查找股票", command=self.start_search, bg="#007acc", fg="white")
        self.search_btn.pack(side=tk.LEFT, padx=10)
        
        self.refresh_btn = tk.Button(input_frame, text="强制刷新数据", command=self.force_refresh, bg="#e74c3c", fg="white")
        self.refresh_btn.pack(side=tk.LEFT, padx=5)
        
        # 数据时间标签
        self.data_time_var = tk.StringVar(value="数据源: 未获取")
        tk.Label(input_frame, textvariable=self.data_time_var, fg="#555555").pack(side=tk.LEFT, padx=10)
        
        # 结果区域
        self.tree = ttk.Treeview(root, columns=('code', 'name', 'current', 'high', 'pct'), show='headings')
        self.tree.heading('code', text='代码')
        self.tree.heading('name', text='名称')
        self.tree.heading('current', text='现价')
        self.tree.heading('high', text='最高')
        self.tree.heading('pct', text='涨跌幅')
        
        self.tree.column('code', width=80, anchor='center')
        self.tree.column('name', width=100, anchor='center')
        self.tree.column('current', width=80, anchor='center')
        self.tree.column('high', width=80, anchor='center')
        self.tree.column('pct', width=80, anchor='center')
        
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 状态栏
        self.status_var = tk.StringVar()
        self.status_var.set("准备就绪")
        tk.Label(root, textvariable=self.status_var, anchor='w', fg="gray").pack(fill=tk.X, padx=10, pady=5)

    def force_refresh(self):
        """清除缓存并强制刷新"""
        self.cached_df = None
        self.cache_time_str = None
        
        # 删除今天的文件缓存
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            cache_file = f"market_data_{today_str}.pkl"
            if os.path.exists(cache_file):
                os.remove(cache_file)
        except Exception as e:
            print(f"清理缓存失败: {e}")
            
        self.data_time_var.set("数据源: 已重置，下次查询将重新拉取")
        messagebox.showinfo("提示", "本地及内存缓存已清除，下次查询将联网获取最新数据。")

    def start_search(self):
        price_str = self.price_entry.get().strip()
        if not price_str:
            messagebox.showwarning("提示", "请输入价格")
            return
        
        try:
            target_price = float(price_str)
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
            return
            
        self.search_btn.config(state='disabled')
        self.refresh_btn.config(state='disabled')
        self.status_var.set(f"正在全市场搜索最高价为 {target_price} 的股票...")
        
        # 清空列表
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        threading.Thread(target=self.run_search, args=(target_price,), daemon=True).start()

    def cleanup_old_cache(self, current_date_str):
        """清理非今日的缓存文件"""
        try:
            for fname in os.listdir('.'):
                if fname.startswith("market_data_") and fname.endswith(".pkl"):
                    # 如果文件名不包含今天的日期，则删除
                    if f"market_data_{current_date_str}.pkl" != fname:
                        try:
                            os.remove(fname)
                        except:
                            pass
        except:
            pass

    def run_search(self, target_price):
        try:
            now_str = datetime.now().strftime("%H:%M:%S")
            today_date = datetime.now().strftime("%Y-%m-%d")
            cache_file = f"market_data_{today_date}.pkl"
            
            # 策略: 内存 -> 本地文件 -> 联网下载
            
            # 1. 优先使用内存缓存
            if self.cached_df is not None and not self.cached_df.empty:
               df = self.cached_df
               source_msg = "内存缓存"
            
            # 2. 其次尝试读取本地文件缓存
            elif os.path.exists(cache_file):
                try:
                    df = pd.read_pickle(cache_file)
                    self.cached_df = df
                    # 获取文件修改时间作为数据时间
                    mtime = os.path.getmtime(cache_file)
                    self.cache_time_str = datetime.fromtimestamp(mtime).strftime("%H:%M:%S")
                    source_msg = "本地文件"
                except Exception:
                    # 文件可能损坏，降级到下载
                    df = ak.stock_zh_a_spot_em()
                    df.to_pickle(cache_file)
                    self.cached_df = df
                    self.cache_time_str = now_str
                    source_msg = "实时(文件修复)"
            
            # 3. 最后联网下载
            else:
               df = ak.stock_zh_a_spot_em()
               # 保存到本地文件
               try:
                   df.to_pickle(cache_file)
                   self.cleanup_old_cache(today_date) # 顺便清理旧文件
               except Exception as e:
                   print(f"写入缓存文件失败: {e}")
                   
               self.cached_df = df
               self.cache_time_str = now_str
               source_msg = "实时下载"
            
            # 筛选最高价匹配的股票 (允许 0.01 的误差)
            # 确保 '最高' 列也是数字类型
            # 注意：部分停牌股票最高价可能为 '-' 或 null
            def check_price(x):
                try:
                    return abs(float(x) - target_price) < 0.01
                except:
                    return False

            mask = df['最高'].apply(check_price)
            result_df = df[mask]
            
            # 回到主线程更新 UI
            self.root.after(0, self.show_results, result_df, source_msg)
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", f"查询失败: {str(e)}"))
            self.root.after(0, lambda: self.status_var.set("查询出错"))
            # 出错清除无效缓存
            self.cached_df = None 
        finally:
            self.root.after(0, lambda: self.search_btn.config(state='normal'))
            self.root.after(0, lambda: self.refresh_btn.config(state='normal'))

    def show_results(self, df, source_msg):
        # 更新时间显示
        time_info = self.cache_time_str if self.cache_time_str else "--:--"
        self.data_time_var.set(f"数据源: {source_msg}数据 ({time_info})")

        if df.empty:
            self.status_var.set("未找到匹配的股票")
            return
            
        count = 0
        for _, row in df.iterrows():
            self.tree.insert('', 'end', values=(
                row['代码'],
                row['名称'],
                row['最新价'],
                row['最高'],
                f"{row['涨跌幅']}%"
            ))
            count += 1
            
        self.status_var.set(f"搜索完成，共找到 {count} 支股票")

if __name__ == "__main__":
    root = tk.Tk()
    app = FindStockApp(root)
    root.mainloop()
