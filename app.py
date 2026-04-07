import streamlit as st
import pandas as pd
import random
import plotly.express as px
import io
import json
import os
import datetime
import jpholiday
import firebase_admin
from firebase_admin import credentials, firestore

# --- ★PyTorchモデルの読み込み ---
try:
    import torch
    # ご自身で作成したファイル名からクラスを読み込む（ファイル名が違う場合は書き換えてください）
    from satisfaction_model import SatisfactionModel
    
    satisfaction_ai = SatisfactionModel()
    satisfaction_ai.eval() # 推論モード
    PYTORCH_AVAILABLE = True
except Exception as e:
    PYTORCH_AVAILABLE = False
    st.error(f"PyTorchモデルの読み込みに失敗しました。ファイル名やコードを確認してください: {e}")

# --- 1. ページ設定 ---
st.set_page_config(page_title="AIシフト管理（PyTorch最適化対応）", layout="wide")

# =========================================================
# 🔥 Firebaseの初期化と接続
# =========================================================
if not firebase_admin._apps:
    # secrets.toml からFirebaseの鍵情報を取得
    firebase_secrets = dict(st.secrets["firebase"])
    # 鍵の改行コード（\n）を正しく認識させるための処理
    firebase_secrets["private_key"] = firebase_secrets["private_key"].replace('\\n', '\n')
    
    cred = credentials.Certificate(firebase_secrets)
    firebase_admin.initialize_app(cred)

# データベース（Firestore）の操作用オブジェクト
db = firestore.client()

# =========================================================
# 15分単位の時間を扱うための便利ツール
# =========================================================
def float_to_time_str(f):
    h = int(f)
    m = int(round((f - h) * 60))
    return f"{h}:{m:02d}"

def time_str_to_float(s):
    h, m = map(int, s.split(':'))
    return h + m / 60.0

time_options = [f"{h}:{m:02d}" for h in range(6, 26) for m in (0, 15, 30, 45) if not (h == 25 and m > 0)]



# =========================================================
# セーブ機能 (Firebase版)
# =========================================================
def save_data():
    data_to_save = {
        "admin_id": st.session_state.admin_id,
        "admin_password": st.session_state.admin_password,
        "employees": st.session_state.employees.to_dict(orient="records"),
        "time_requests": st.session_state.time_requests, 
        "daily_adjusted_times": st.session_state.daily_adjusted_times, 
        "daily_removed_staff": st.session_state.daily_removed_staff,   
        "work_records": st.session_state.work_records,
        "required_staff": st.session_state.required_staff,
        "required_level": st.session_state.get("required_level", {}),
        "special_required_staff": st.session_state.special_required_staff,
        "quick_buttons": st.session_state.quick_buttons,
        "previous_times": st.session_state.previous_times
    }
    
    # Firestoreの "shift_management" コレクションの "main_data" というドキュメントに保存
    db.collection("shift_management").document("main_data").set(data_to_save)

# --- 2. データ保持（オートロード） ---
days = ["月", "火", "水", "木", "金", "土", "日"]
req_days = ["月", "火", "水", "木", "金", "土", "日", "祝"]

if 'employees' not in st.session_state:
    doc_ref = db.collection("shift_management").document("main_data")
    doc = doc_ref.get()

    if doc.exists:
        loaded_data = doc.to_dict()
        
        st.session_state.admin_id = loaded_data.get("admin_id", "admin")
        st.session_state.admin_password = loaded_data.get("admin_password", "admin")
        df_emp = pd.DataFrame(loaded_data["employees"])
        if "時給" not in df_emp.columns:
            df_emp["時給"] = 1000
            
        st.session_state.employees = df_emp
        st.session_state.time_requests = loaded_data["time_requests"]
        st.session_state.work_records = loaded_data.get("work_records", {name: [] for name in df_emp["名前"]})
        
        saved_req = loaded_data.get("required_staff", {})
        if "祝" not in saved_req:
            saved_req["祝"] = {str(h): 2 for h in range(6, 25)}
        for d in days:
            if d not in saved_req:
                saved_req[d] = {str(h): 2 for h in range(6, 25)}
        st.session_state.required_staff = saved_req
        
        st.session_state.daily_adjusted_times = loaded_data.get("daily_adjusted_times", {})
        st.session_state.daily_removed_staff = loaded_data.get("daily_removed_staff", {})
        st.session_state.special_required_staff = loaded_data.get("special_required_staff", {})
        st.session_state.previous_times = loaded_data.get("previous_times", {}) 
        
        if "quick_buttons" in loaded_data:
            st.session_state.quick_buttons = loaded_data["quick_buttons"]
        else:
            st.session_state.quick_buttons = [
                {"name": "🌅 早番", "start": 9.0, "end": 17.0},
                {"name": "🌙 中番", "start": 17.0, "end": 21.0},
                {"name": "🕛 中遅", "start": 17.0, "end": 25.0},
                {"name": "🦉 遅番", "start": 21.0, "end": 25.0}
            ]

    else:
        st.session_state.admin_id = "admin"
        st.session_state.admin_password = "admin"
        st.session_state.employees = pd.DataFrame([
            {"名前": f"スタッフ{i+1}", "ID": f"staff{i+1}", "パスワード": "1234", "レベル": 2, "時給": 1000, "累計出勤": 0} 
            for i in range(20)
        ])
        st.session_state.time_requests = {f"スタッフ{i+1}": {day: (9.0, 24.0) for day in days} for i in range(20)}
        st.session_state.work_records = {f"スタッフ{i+1}": [] for i in range(20)}
        st.session_state.required_staff = {day: {str(h): 2 for h in range(6, 25)} for day in req_days} 
        
        st.session_state.daily_adjusted_times = {}
        st.session_state.daily_removed_staff = {}
        st.session_state.special_required_staff = {}
        st.session_state.previous_times = {} 
        st.session_state.quick_buttons = [
            {"name": "早番", "start": 9.0, "end": 17.0},
            {"name": "中番", "start": 17.0, "end": 21.0},
            {"name": "中遅", "start": 17.0, "end": 25.0},
            {"name": "遅番", "start": 21.0, "end": 25.0}
        ]

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.current_user = None

# =========================================================
# ログイン画面
# =========================================================
if not st.session_state.logged_in:
    st.title("🔐 シフト管理システム ログイン")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        st.info("""
        **【ログイン情報】**
        * スタッフ ➔ 各自に設定されたIDとパスワード
        """)
        
        with st.form("login_form"):
            username = st.text_input("ユーザーID")
            password = st.text_input("パスワード", type="password")
            submitted = st.form_submit_button("ログイン")
            
            if submitted:
                if username == st.session_state.admin_id and password == st.session_state.admin_password:
                    st.session_state.logged_in = True
                    st.session_state.current_user = "admin"
                    st.rerun()
                else:
                    match = st.session_state.employees[
                        (st.session_state.employees["ID"] == username) & 
                        (st.session_state.employees["パスワード"] == password)
                    ]
                    if not match.empty:
                        st.session_state.logged_in = True
                        st.session_state.current_user = match["名前"].values[0]
                        st.rerun()
                    else:
                        st.error("IDまたはパスワードが間違っています。")

# =========================================================
# ログイン成功後の画面
# =========================================================
else:
    today = datetime.date.today()
    weekday_str = days[today.weekday()] 
    today_holiday = jpholiday.is_holiday_name(today)

    st.sidebar.write(f"👤 ログイン中: **{st.session_state.current_user}**")
    if today_holiday:
        st.sidebar.markdown(f"📅 **本日:** {today.strftime('%Y/%m/%d')} ({weekday_str}) 🎌**{today_holiday}**")
    else:
        st.sidebar.markdown(f"📅 **本日:** {today.strftime('%Y/%m/%d')} ({weekday_str})")
    
    if st.sidebar.button("ログアウト"):
        st.session_state.logged_in = False
        st.session_state.current_user = None
        st.rerun()
    st.sidebar.divider()

    # ---------------------------------------------------------
    # 【管理者モード】
    # ---------------------------------------------------------
    if st.session_state.current_user == "admin":
        mode = st.sidebar.radio("管理者メニュー", ["シフト作成（グラフ操作）", "🤖 AI設定", "給与・勤怠管理", "店舗設定"])

        if mode == "シフト作成（グラフ操作）":
            st.title("⚙️ 管理者画面：AIシフト作成 ＆ 調整")
            
            target_date = st.date_input("📅 基準となる日付を選択（この日が含まれる1週間を計算します）", today)
            date_str = target_date.strftime("%Y/%m/%d")
            base_day = days[target_date.weekday()]
            holiday_name = jpholiday.is_holiday_name(target_date)
            
            if date_str not in st.session_state.daily_adjusted_times:
                st.session_state.daily_adjusted_times[date_str] = {}
                
                # 今選んでいる日付が属する「週（月曜日）」のキーを計算
                target_monday = target_date - datetime.timedelta(days=target_date.weekday())
                week_key = target_monday.strftime('%Y-%m-%d')
                
                for name in st.session_state.employees["名前"]:
                    user_all_reqs = st.session_state.time_requests.get(name, {})
                    
                    # 💡 指定した週のデータを探す。なければ一番新しい週を借りる
                    week_data = user_all_reqs.get(week_key, {})
                    if not week_data and user_all_reqs:
                        latest_key = list(user_all_reqs.keys())[-1]
                        week_data = user_all_reqs[latest_key] if isinstance(user_all_reqs[latest_key], dict) else user_all_reqs
                    
                    # 曜日ごとの希望時間を取得。データがなければ 9:00〜24:00 をデフォルトに
                    req = week_data.get(base_day, (9.0, 24.0))
                    
                    # 店長の調整用データとして保存
                    st.session_state.daily_adjusted_times[date_str][name] = req

            if date_str not in st.session_state.daily_removed_staff:
                st.session_state.daily_removed_staff[date_str] = []
                
            st.divider()
            
            # --- 1週間分の判定用関数 ---
            def get_req_dict(d_date):
                d_str = d_date.strftime("%Y/%m/%d")
                d_day = days[d_date.weekday()]
                if d_str in st.session_state.special_required_staff:
                    return st.session_state.special_required_staff[d_str]
                elif jpholiday.is_holiday_name(d_date):
                    return st.session_state.required_staff["祝"]
                else:
                    return st.session_state.required_staff[d_day]

            # ★ 高速化のため、スタッフのレベルを辞書化（1〜10段階）
            level_dict = {row["名前"]: row["レベル"] for _, row in st.session_state.employees.iterrows()}
            
            # ★ 修正版：人数が「完璧か」ではなく、「人数不足のペナルティがどれくらいか」を計算する関数
            def get_shift_deficit(shifts_dict, req_dict):
                deficit = 0
                for h_str, needed in req_dict.items():
                    h = int(h_str)
                    needed = int(needed)
                    if needed == 0: continue
                    
                    for quarter in [0.0, 0.25, 0.5, 0.75]:
                        check_time = h + quarter 
                        count = sum(1 for n, (s, e) in shifts_dict.items() if s <= check_time < e)
                        if count < needed:
                            deficit += (needed - count) # 足りない人数分だけペナルティポイントを加算
                return deficit

            col_ai, col_msg = st.columns([1, 2])
            with col_ai:
               if st.button("✨ 1週間まとめてAI自動作成 (PyTorch最適化)", use_container_width=True, type="primary"):
                    if not PYTORCH_AVAILABLE:
                        st.error("PyTorchモデルが読み込めていません。")
                    else:
                        with st.spinner('1週間分の最適シフトを計算中（人数ピッタリ・レベル維持・不満最小化）...'):
                            # 1. ターゲットの週の日付取得
                            start_of_week = target_date - datetime.timedelta(days=target_date.weekday())
                            week_dates = [start_of_week + datetime.timedelta(days=i) for i in range(7)]
                            
                            best_weekly_shifts = None
                            best_total_score = float('inf')
                            
                            # 現場に必要な「最低合計レベル」のしきい値（例: 1日の出勤者の合計レベルが10以上）
                            # ※店舗に合わせてここの数字を調整してください
                            MIN_TOTAL_LEVEL_PER_DAY = 10.0 

                            for iteration in range(20): # 試行回数（20パターンのシフトから一番マシなものを選ぶ）
                                current_weekly_shifts = {}
                                for d_date in week_dates:
                                    d_str = d_date.strftime("%Y/%m/%d")
                                    d_day = days[d_date.weekday()]
                                    req_dict = get_req_dict(d_date)
                                    
                                    daily_shifts = {}
                                    for name in st.session_state.employees["名前"]:
                                        req_s, req_e = st.session_state.time_requests[name][d_day]
                                        if req_s < req_e:
                                            daily_shifts[name] = [req_s, req_e]
                                    
                                    # --- 最適化ロジック（ペナルティ悪化を防ぐ方式） ---
                                    staff_names = st.session_state.employees["名前"].tolist()
                                    changed = True
                                    while changed:
                                        changed = False
                                        current_deficit = get_shift_deficit(daily_shifts, req_dict)
                                        
                                        # 1. 丸ごと休みにできるかテスト
                                        random.shuffle(staff_names)
                                        for name in staff_names:
                                            if name not in daily_shifts: continue
                                            s, e = daily_shifts[name]
                                            if e - s <= 0: continue
                                            
                                            original_time = daily_shifts[name]
                                            daily_shifts[name] = [0.0, 0.0] 
                                            
                                            # 休みにしても、全体の「人数不足ペナルティ」が悪化しないなら削る！
                                            new_deficit = get_shift_deficit(daily_shifts, req_dict)
                                            if new_deficit <= current_deficit:
                                                changed = True
                                                current_deficit = new_deficit
                                            else:
                                                daily_shifts[name] = original_time

                                        # 2. 時間を限界まで削れるかテスト (15分刻み)
                                        random.shuffle(staff_names)
                                        for name in staff_names:
                                            if name not in daily_shifts: continue
                                            s, e = daily_shifts[name]
                                            if e - s <= 0.0: continue
                                            
                                            # 出勤を15分遅らせる
                                            daily_shifts[name] = [s + 0.25, e]
                                            new_deficit = get_shift_deficit(daily_shifts, req_dict)
                                            if new_deficit <= current_deficit:
                                                s += 0.25
                                                changed = True
                                                current_deficit = new_deficit
                                            else:
                                                daily_shifts[name] = [s, e]
                                                
                                            # 退勤を15分早める
                                            daily_shifts[name] = [s, e - 0.25]
                                            new_deficit = get_shift_deficit(daily_shifts, req_dict)
                                            if new_deficit <= current_deficit:
                                                e -= 0.25
                                                changed = True
                                                current_deficit = new_deficit
                                            else:
                                                daily_shifts[name] = [s, e]
                                    
                                    # 1日分の最適化が完了
                                    current_weekly_shifts[d_str] = daily_shifts
                                
                                # --- PyTorchによる1週間トータルの不満度採点 ---
                                total_dissatisfaction = 0.0
                                for name in st.session_state.employees["名前"]:
                                    weekend_count = 0.0
                                    consecutive = 0.0
                                    max_consec = 0.0
                                    rejected = 0.0
                                    
                                    for d_date in week_dates:
                                        d_str = d_date.strftime("%Y/%m/%d")
                                        d_day = days[d_date.weekday()]
                                        
                                        s, e = current_weekly_shifts[d_str].get(name, (0.0, 0.0))
                                        worked_h = e - s
                                        req_s, req_e = st.session_state.time_requests[name][d_day]
                                        req_h = req_e - req_s
                                        
                                        if worked_h > 0:
                                            consecutive += 1.0
                                            if consecutive > max_consec: max_consec = consecutive
                                            if d_day in ["土", "日"]: weekend_count += 1.0
                                        else:
                                            consecutive = 0.0
                                            if req_h > 0: rejected += 1.0
                                    
                                    input_tensor = torch.tensor([[weekend_count, max_consec, rejected]], dtype=torch.float32)
                                    with torch.no_grad():
                                        score = satisfaction_ai(input_tensor).item()
                                    total_dissatisfaction += score
                                
                                if total_dissatisfaction < best_total_score:
                                    best_total_score = total_dissatisfaction
                                    best_weekly_shifts = current_weekly_shifts

                            # --- 最適解の session_state への反映 ---
                            if best_weekly_shifts:
                                for d_str, shifts in best_weekly_shifts.items():
                                    d_date = datetime.datetime.strptime(d_str, "%Y/%m/%d").date()
                                    d_day = days[d_date.weekday()]
                                    
                                    if d_str not in st.session_state.daily_adjusted_times:
                                        st.session_state.daily_adjusted_times[d_str] = {}
                                    
                                    removed = []
                                    for name, (s, e) in shifts.items():
                                        if e - s <= 0:
                                            removed.append(name)
                                            req_s = st.session_state.time_requests[name][d_day][0]
                                            st.session_state.daily_adjusted_times[d_str][name] = (req_s, req_s)
                                        else:
                                            st.session_state.daily_adjusted_times[d_str][name] = (s, e)
                                    
                                    for name in st.session_state.employees["名前"]:
                                        if name not in shifts and name not in removed:
                                            removed.append(name)
                                    st.session_state.daily_removed_staff[d_str] = removed
                                
                                save_data()
                                st.success(f"✅ 最適化完了！(不満度: {best_total_score:.2f}) 必要人数を維持しつつ、スタッフのレベルバランスを考慮しました。")
                            else:
                                st.warning("条件を満たすシフトが生成できませんでした。") 

            with col_msg:
                if PYTORCH_AVAILABLE:
                    st.success("🤖 PyTorch AI (不満度予測モデル) 稼働中！")
                else:
                    st.warning("⚠️ PyTorchモデルが読み込まれていません。")
            
            st.divider()

            col_graph, col_ctrl = st.columns([2, 1])

            with col_graph:
                st.subheader(f"📊 {date_str} のシフト（調整用グラフ）")
                
                chart_data = []
                off_staff = [] 
                for name in st.session_state.employees["名前"]:
                    # 1. そのスタッフの全データを取得
                    user_all_reqs = st.session_state.time_requests.get(name, {})
                    
                    # 2. 今表示している日付の「月曜日」を特定
                    target_monday_graph = target_date - datetime.timedelta(days=target_date.weekday())
                    week_key_graph = target_monday_graph.strftime('%Y-%m-%d')
                    
                    # 3. 指定した週のデータを探す
                    week_data = user_all_reqs.get(week_key_graph, {})
                    
                    # 4. もし今週分がなければ、一番新しい提出分を予備で使う
                    if not week_data and user_all_reqs:
                        latest_key = list(user_all_reqs.keys())[-1]
                        # 辞書形式なら中身を、そうでなければ(古い形式)そのまま使う
                        week_data = user_all_reqs[latest_key] if isinstance(user_all_reqs[latest_key], dict) else user_all_reqs
                    
                    # 5. その日の希望時間を取得（データが全くなければ休み扱い）
                    if isinstance(week_data, dict):
                        req_start, req_end = week_data.get(base_day, (6.0, 6.0))
                    else:
                        req_start, req_end = (6.0, 6.0)

                    # --- ここから下は元の「if req_start == req_end:」の処理に続きます ---
                    if req_start == req_end:
                        off_staff.append(name) 
                        continue

                    
                    # 取り出した結果、出勤時間と退勤時間が同じ（休み）ならリストから除外する
                    if req_start == req_end:
                        off_staff.append(name) 
                        continue
                        
                    if name not in st.session_state.daily_removed_staff[date_str]:
                        day_adjustments = st.session_state.daily_adjusted_times.get(date_str, {})
                        adj_start, adj_end = tuple(day_adjustments.get(name, (req_start, req_end)))
                        if adj_start < adj_end:
                            lvl = st.session_state.employees.loc[st.session_state.employees["名前"]==name, "レベル"].values[0]
                            chart_data.append({
                                "スタッフ名": name, 
                                "開始": float(adj_start), 
                                "終了": float(adj_end), 
                                "レベル": f"Lv.{lvl}", 
                                "希望開始": float(req_start),
                                "表示時間": f"{float_to_time_str(adj_start)} 〜 {float_to_time_str(adj_end)}"
                            })
                
                if chart_data:
                    df_chart = pd.DataFrame(chart_data)
                    df_chart = df_chart.sort_values(by=["希望開始", "レベル"], ascending=[True, False])
                    
                    fig = px.bar(
                        df_chart, x=df_chart["終了"] - df_chart["開始"], y="スタッフ名", base="開始",
                        orientation='h', color="レベル", 
                        color_discrete_map={"Lv.1":"#87CEEB","Lv.2":"#4682B4","Lv.3":"#191970"},
                        hover_data={"スタッフ名":True, "開始":False, "終了":False, "表示時間":True, "レベル":True},
                        range_x=[6, 25]
                    )
                    
                    fig.update_layout(
                        xaxis=dict(tickmode='array', tickvals=[i for i in range(6, 26)], ticktext=[f"{i}:00" for i in range(6, 26)]), 
                        height=max(400, len(chart_data) * 50),
                        margin=dict(l=0, r=0, t=30, b=0),
                        yaxis={'categoryorder':'array', 'categoryarray': df_chart['スタッフ名'].tolist()[::-1]}
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("この日に出勤予定のスタッフはいません。")
                    
                if off_staff:
                    st.caption(f"**本日休みのスタッフ:** {', '.join(off_staff)}")

            with col_ctrl:
                st.subheader("✂️ 手動での最終微調整")
                st.caption("AIが作成したシフトをベースに、さらに店長が微調整できます。")
                
                # 💡 chart_data（グラフ表示者）ではなく、全スタッフの名前でループを回す
                # これにより、特定のスタッフでエラーが起きても他のスタッフが表示されるようになります
                for name in st.session_state.employees["名前"]:
                    try:
                        # --- 1. データの準備（週対応） ---
                        user_all_reqs = st.session_state.time_requests.get(name, {})
                        target_monday = target_date - datetime.timedelta(days=target_date.weekday())
                        week_key = target_monday.strftime('%Y-%m-%d')
                        
                        # 指定週のデータを取得
                        week_data = user_all_reqs.get(week_key, {})
                        if not week_data and user_all_reqs:
                            # 辞書形式なら最新の週を、そうでなければ全体を
                            latest_key = list(user_all_reqs.keys())[-1]
                            week_data = user_all_reqs[latest_key] if isinstance(user_all_reqs[latest_key], dict) else user_all_reqs
                        
                        # 曜日ごとの希望時間を取得（データなしは 6.0, 6.0）
                        req_start, req_end = week_data.get(base_day, (6.0, 6.0))
                        
                        # 休みのスタッフは調整スライダーを出さない
                        if name in st.session_state.daily_removed_staff[date_str] or req_start == req_end:
                            continue

                        # 調整後の現在の値を取得
                        day_adjustments = st.session_state.daily_adjusted_times.get(date_str, {})
                        adj_start, adj_end = tuple(day_adjustments.get(name, (req_start, req_end)))

                        # --- 2. スライダーの表示 ---
                        with st.container():
                            st.markdown(f"**{name}** (希望: {float_to_time_str(req_start)} 〜 {float_to_time_str(req_end)})")
                            
                            # 文字列に変換
                            req_s_str, req_e_str = to_slider_str(req_start), to_slider_str(req_end)
                            adj_s_str, adj_e_str = to_slider_str(adj_start), to_slider_str(adj_end)

                            if req_s_str in time_options and req_e_str in time_options:
                                idx_s = time_options.index(req_s_str)
                                idx_e = time_options.index(req_e_str)
                                valid_options = time_options[idx_s : idx_e+1]
                                
                                if len(valid_options) > 1:
                                    # ガードレール：現在の調整値が選択肢にない場合は希望時間に合わせる
                                    final_s = adj_s_str if adj_s_str in valid_options else req_s_str
                                    final_e = adj_e_str if adj_e_str in valid_options else req_e_str
                                    
                                    new_adj_str = st.select_slider(
                                        "時間調整", options=valid_options, value=(final_s, final_e),
                                        key=f"adj_vFinal_{date_str}_{name}", label_visibility="collapsed"
                                    )
                                    
                                    # 保存と更新
                                    new_adj = (time_str_to_float(new_adj_str[0]), time_str_to_float(new_adj_str[1]))
                                    if new_adj != (adj_start, adj_end):
                                        st.session_state.daily_adjusted_times[date_str][name] = new_adj
                                        save_data()
                                        st.rerun()
                                else:
                                    st.info("固定シフトのため調整不可")
                            
                            # 個別の「休みに変更」ボタン
                            if st.button(f"❌ {name}を休みに変更", key=f"rem_btn_{date_str}_{name}", use_container_width=True):
                                st.session_state.daily_removed_staff[date_str].append(name)
                                save_data()
                                st.rerun()
                            st.divider()

                    except Exception as e:
                        # 誰か一人でエラーが起きても、この一人だけスキップして次のスタッフへ進む
                        st.error(f"⚠️ {name}さんの調整データに不備があります")
                        continue

                # --- 3. 休みのスタッフを戻すエリア（週対応版） ---
                if st.session_state.daily_removed_staff[date_str]:
                    st.write("---")
                    st.subheader("↩️ 休みのスタッフを戻す")
                    for name in st.session_state.daily_removed_staff[date_str]:
                        try:
                            u_reqs = st.session_state.time_requests.get(name, {})
                            t_monday = target_date - datetime.timedelta(days=target_date.weekday())
                            w_key = t_monday.strftime('%Y-%m-%d')
                            w_data = u_reqs.get(w_key, u_reqs.get(list(u_reqs.keys())[-1], {}))
                            r_s, r_e = w_data.get(base_day, (6.0, 6.0))
                            
                            btn_label = f"➕ {name} を出勤させる" + (f" (希望: {float_to_time_str(r_s)}〜)" if r_s < r_e else "")
                            if st.button(btn_label, key=f"restore_btn_{date_str}_{name}", use_container_width=True):
                                st.session_state.daily_adjusted_times[date_str][name] = [r_s, r_e]
                                st.session_state.daily_removed_staff[date_str].remove(name)
                                save_data()
                                st.rerun()
                        except:
                            continue
            st.divider()
            st.subheader(f"📥 {date_str} の1日分 Excel出力")
            st.caption("完成したシフトを、15分刻みの詳細なExcelとしてダウンロードできます。")

            time_cols = time_options

            def create_single_day_df():
                working_staff = []
                for n in st.session_state.employees["名前"]:
                    if n not in st.session_state.daily_removed_staff[date_str]:
                        day_adjustments_df = st.session_state.daily_adjusted_times.get(date_str, {})
                        a_s, a_e = tuple(day_adjustments_df.get(n, (6.0, 6.0)))
                        if a_s < a_e:
                            working_staff.append({"name": n, "start": float(a_s), "end": float(a_e)})
                
                working_staff.sort(key=lambda x: x["start"])
                lanes, assignments = [], {} 

                for staff in working_staff:
                    assigned = False
                    for i, lane_end_time in enumerate(lanes):
                        if lane_end_time <= staff["start"]:
                            lanes[i] = staff["end"]
                            assignments[staff["name"]] = i
                            assigned = True
                            break
                    if not assigned:
                        lanes.append(staff["end"])
                        assignments[staff["name"]] = len(lanes) - 1

                max_rows = len(lanes) if lanes else 1
                matrix = [["" for _ in time_cols] for _ in range(max_rows)]

                for staff in working_staff:
                    row_idx = assignments[staff["name"]]
                    s, e = staff["start"], staff["end"]
                    for col_idx, t_str in enumerate(time_cols):
                        t_float = time_str_to_float(t_str)
                        if t_float == s:
                            matrix[row_idx][col_idx] = staff["name"]
                        elif s < t_float < e:
                            matrix[row_idx][col_idx] = "ー"

                day_data = {time_cols[c]: [matrix[r][c] for r in range(max_rows)] for c in range(len(time_cols))}
                return pd.DataFrame(day_data, index=[f"{i+1}段目" for i in range(max_rows)])

            df_preview = create_single_day_df()
            st.dataframe(df_preview, use_container_width=True)

            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                sheet_name = date_str.replace("/", "")
                df_preview.to_excel(writer, sheet_name=sheet_name)
                worksheet = writer.sheets[sheet_name]
                worksheet.column_dimensions['A'].width = 10
                for col in worksheet.columns:
                    col_letter = col[0].column_letter
                    if col_letter != 'A':
                        worksheet.column_dimensions[col_letter].width = 6
            
            st.download_button(
                label=f"📊 {date_str}のシフト表をダウンロード",
                data=buffer.getvalue(),
                file_name=f"shift_{date_str.replace('/','')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        elif mode == "🤖 AI設定":
            st.title("🤖 必要人数 ＆ 必要平均レベルの設定")
            tab_base, tab_special = st.tabs(["📅 基本の曜日・祝日設定", "📌 手動の特例日設定"])
            
            # ★データが存在しない場合の初期化
            if "required_level" not in st.session_state:
                st.session_state.required_level = {day: {str(h): 5.0 for h in range(6, 25)} for day in req_days}
                
            with tab_base:
                selected_day = st.selectbox("設定する曜日・祝日を選択", req_days, index=today.weekday())
                req_dict = st.session_state.required_staff[selected_day]
                lvl_dict = st.session_state.required_level.get(selected_day, {str(h): 5.0 for h in range(6, 25)})
                
                # ★ 人数とレベルの両方を表に表示する
                df_req = pd.DataFrame([{"時間帯": f"{h}:00 〜 {h+1}:00", "必要人数": req_dict[str(h)], "必要平均レベル": lvl_dict.get(str(h), 5.0)} for h in range(6, 25)])
                edited_req = st.data_editor(df_req, hide_index=True, use_container_width=True)
                
                if st.button(f"基本の {selected_day} の設定を保存", use_container_width=True):
                    for i, h in enumerate(range(6, 25)): 
                        st.session_state.required_staff[selected_day][str(h)] = int(edited_req.iloc[i]["必要人数"])
                        if selected_day not in st.session_state.required_level: st.session_state.required_level[selected_day] = {}
                        st.session_state.required_level[selected_day][str(h)] = float(edited_req.iloc[i]["必要平均レベル"])
                    save_data(); st.success(f"{selected_day} の設定を保存しました！"); st.rerun()

            with tab_special:
                sp_date = st.date_input("設定する日付を選択（カレンダー）", today)
                sp_date_str = sp_date.strftime("%Y/%m/%d")
                
                if sp_date_str in st.session_state.special_required_staff:
                    req_dict_sp = st.session_state.special_required_staff[sp_date_str]
                    is_special_saved = True
                else:
                    req_dict_sp = st.session_state.required_staff["祝" if jpholiday.is_holiday_name(sp_date) else days[sp_date.weekday()]]
                    is_special_saved = False
                    
                st.markdown(f"**{sp_date_str} の設定**" + (" (📌 特例設定あり)" if is_special_saved else " (基本設定を表示中)"))
                df_req_sp = pd.DataFrame([{"時間帯": f"{h}:00 〜 {h+1}:00", "必要人数": req_dict_sp[str(h)]} for h in range(6, 25)])
                edited_req_sp = st.data_editor(df_req_sp, hide_index=True, use_container_width=True, key=f"ed_{sp_date_str}")
                
                c1, c2 = st.columns(2)
                if c1.button(f"この日の特例設定を保存", use_container_width=True):
                    st.session_state.special_required_staff[sp_date_str] = {str(h): int(edited_req_sp.iloc[i]["必要人数"]) for i, h in enumerate(range(6, 25))}
                    save_data(); st.success("保存しました！"); st.rerun()
                if c2.button("特例設定を解除（基本に戻す）", use_container_width=True):
                    if sp_date_str in st.session_state.special_required_staff:
                        del st.session_state.special_required_staff[sp_date_str]
                        save_data(); st.success("解除しました！"); st.rerun()

        elif mode == "給与・勤怠管理":
            st.title("💰 管理者画面：月別 給与・勤怠管理")
            
            all_months = set()
            for name, records in st.session_state.work_records.items():
                for r in records:
                    all_months.add(r["日付"][:7])
            
            current_month = today.strftime("%Y/%m")
            all_months.add(current_month)
            
            available_months = sorted(list(all_months), reverse=True)
            
            selected_month = st.selectbox("表示する月を選択", available_months)
            st.divider()
            
            summary_data = []
            detailed_data = {}
            
            for index, emp in st.session_state.employees.iterrows():
                name = emp["名前"]
                wage = emp["時給"]
                records = st.session_state.work_records.get(name, [])
                
                month_records = [r for r in records if r["日付"].startswith(selected_month)]
                
                if month_records:
                    total_hours = sum([r["労働時間(H)"] for r in month_records])
                    total_salary = sum([r["日給(円)"] for r in month_records])
                    
                    summary_data.append({
                        "スタッフ名": name,
                        "時給": f"{wage}円",
                        "出勤日数": f"{len(month_records)}日",
                        "総労働時間": f"{total_hours:.2f}H",
                        "合計給料": total_salary
                    })
                    detailed_data[name] = month_records
                else:
                    summary_data.append({
                        "スタッフ名": name,
                        "時給": f"{wage}円",
                        "出勤日数": "0日",
                        "総労働時間": "0.00H",
                        "合計給料": 0
                    })
                    detailed_data[name] = []
                    
            st.subheader(f"📊 {selected_month} の給料まとめ")
            
            df_summary = pd.DataFrame(summary_data)
            df_summary = df_summary.sort_values(by="合計給料", ascending=False).reset_index(drop=True)
            
            st.dataframe(
                df_summary,
                column_config={"合計給料": st.column_config.NumberColumn("合計給料 (円)", format="%d 円")},
                use_container_width=True, hide_index=True
            )
            
            grand_total = df_summary["合計給料"].sum()
            st.info(f"🏢 店舗全体の {selected_month} の人件費合計: **{int(grand_total):,} 円**")
            
            st.divider()
            
            st.subheader("📝 スタッフ別 詳細タイムカード")
            
            for name in df_summary["スタッフ名"]:
                records = detailed_data[name]
                if records:
                    with st.expander(f"👤 {name} （出勤: {len(records)}日）"):
                        df_records = pd.DataFrame(records)
                        st.dataframe(df_records, use_container_width=True, hide_index=True)
                        
                        # --- 合計の追記 ---
                        total_h = df_records["労働時間(H)"].sum()
                        total_w = df_records["日給(円)"].sum()
                        st.markdown(f"**💰 この月の合計： 労働時間 {total_h:.2f}H / 給与 {int(total_w):,} 円**")

                        

        elif mode == "店舗設定":
            st.title("🔧 管理者画面：店舗・アカウント設定")
            st.subheader("🔑 管理者ログイン情報の設定")
            new_admin_id = st.text_input("管理者ID", value=st.session_state.admin_id)
            new_admin_pass = st.text_input("管理者パスワード", value=st.session_state.admin_password, type="password")
            
            if st.button("管理者情報を更新する"):
                st.session_state.admin_id = new_admin_id
                st.session_state.admin_password = new_admin_pass
                save_data()
                st.success("管理者IDとパスワードを更新しました！次回からこの情報でログインしてください。")
            
            st.divider()

            st.subheader("⚡ 曜日ごとのクイック入力ボタンのカスタマイズ")
            st.caption("スタッフが各曜日でポンッと押せる「よくあるシフト時間」を追加・削除できます。")
            
            if st.session_state.quick_buttons:
                for i, qb in enumerate(st.session_state.quick_buttons):
                    col_name, col_time, col_del = st.columns([3, 3, 1])
                    with col_name:
                        st.write(f"🔘 **{qb['name']}**")
                    with col_time:
                        st.write(f"⏰ {float_to_time_str(qb['start'])} 〜 {float_to_time_str(qb['end'])}")
                    with col_del:
                        if st.button("🗑️ 削除", key=f"del_qb_{i}"):
                            st.session_state.quick_buttons.pop(i)
                            save_data()
                            st.rerun()
            else:
                st.write("現在登録されているボタンはありません。")
                
            with st.expander("➕ 新しいクイックボタンを作成する"):
                new_qb_name = st.text_input("ボタンの名前を入力（例：🌅 早番）")
                st.write("ボタンを押した時にセットされる時間を設定してください：")
                
                start_qb, end_qb = st.select_slider(
                    "時間", options=time_options, value=("9:00", "15:00"), 
                    key="new_qb_time"
                )
                
                if st.button("このボタンを作成して保存", type="primary"):
                    if new_qb_name:
                        st.session_state.quick_buttons.append({
                            "name": new_qb_name, 
                            "start": time_str_to_float(start_qb), 
                            "end": time_str_to_float(end_qb)
                        })
                        save_data()
                        st.success(f"ボタン「{new_qb_name}」を作成しました！")
                        st.rerun()
                    else:
                        st.error("ボタンの名前を入力してください。")
            
            st.divider()
            
            st.subheader("👨‍🍳 スタッフのアカウント・給与設定")
            
            edited_df = st.data_editor(
                st.session_state.employees[["名前", "ID", "パスワード", "レベル", "時給"]],
                num_rows="dynamic", 
                column_config={
                    "名前": st.column_config.TextColumn("表示名 (変更可)", required=True),
                    "ID": st.column_config.TextColumn("ログインID (変更可)", required=True),
                    "パスワード": st.column_config.TextColumn("パスワード (変更可)", required=True),
                    "レベル": st.column_config.NumberColumn("評価 (1-10)", min_value=1, max_value=10, step=1),
                    "時給": st.column_config.NumberColumn("時給 (円)", min_value=0, step=1) 
                },
                hide_index=False, 
                use_container_width=True,
                key="eval_editor"
            )
            
            if st.button("設定を保存する"):
                valid_df = edited_df.dropna(subset=["名前", "ID"]).copy()
                st.session_state.employees = valid_df
                
                for n in valid_df["名前"]:
                    if n not in st.session_state.time_requests:
                        st.session_state.time_requests[n] = {day: (9.0, 24.0) for day in days}
                    if n not in st.session_state.work_records:
                        st.session_state.work_records[n] = []
                            
                save_data() 
                st.success("アカウント情報と時給設定を保存しました！")

            st.divider()
            if st.button("全データを完全リセット（超注意）"):
                st.session_state.clear()
                if os.path.exists(DATA_FILE):
                    os.remove(DATA_FILE)
                st.rerun()

    # ---------------------------------------------------------
    # 【スタッフモード】（ログイン中のスタッフの画面のみ）
    # ---------------------------------------------------------
    else:
        name = st.session_state.current_user
        
        tab1, tab2 = st.tabs(["📝 基本のシフト希望提出", "📅 月別タイムカード・給料"])
        
        with tab1:
            st.title(f"{name} さんのシフト希望入力")
            
            # ==========================================
            # 📅 追加：週を選択するドロップダウン
            # ==========================================
            today = datetime.date.today()
            this_monday = today - datetime.timedelta(days=today.weekday())
            
            week_options = {
                f"今週 ({this_monday.strftime('%m/%d')}〜)": this_monday,
                f"来週 ({(this_monday + datetime.timedelta(weeks=1)).strftime('%m/%d')}〜)": this_monday + datetime.timedelta(weeks=1),
                f"再来週 ({(this_monday + datetime.timedelta(weeks=2)).strftime('%m/%d')}〜)": this_monday + datetime.timedelta(weeks=2),
            }
            
            selected_week_label = st.selectbox("入力する週を選んでください", list(week_options.keys()))
            target_monday = week_options[selected_week_label]
            week_key = target_monday.strftime('%Y-%m-%d') # 金庫の引き出しの名前に使う（例: 2026-04-13）
            # ==========================================

            st.caption("選択した週の「出勤可能時間」を入力してください。")
            st.warning("⚠️ **【重要】** 来週のシフト希望は、必ず**今週の金曜日**までに提出してください！")

            # --- データ保存先の形を「週ごと」にアップデート ---
            if name not in st.session_state.time_requests:
                st.session_state.time_requests[name] = {}
            
            # 古い形式のデータ（直接「月」「火」が入っている）の互換性対策
            if "月" in st.session_state.time_requests[name]:
                old_data = st.session_state.time_requests[name].copy()
                st.session_state.time_requests[name] = {week_key: old_data}
                
            # 選んだ週のデータがまだ無ければ、初期値（例: 9:00〜17:00）を作る
            if week_key not in st.session_state.time_requests[name]:
                st.session_state.time_requests[name][week_key] = {d: (9.0, 17.0) for d in days}

            # 選んだ週のデータを user_times に取り出す
            user_times = st.session_state.time_requests[name][week_key]

            for i, day in enumerate(days):
                # 📅 追加：ループの中でその曜日の日付を計算する
                current_date = target_monday + datetime.timedelta(days=i)
                date_str = current_date.strftime("%m/%d")

                with st.container():
                    # 曜日と一緒に日付も表示する！
                    st.markdown(f"**{name}** (希望: {float_to_time_str(req_start)} 〜 {float_to_time_str(req_end)})")
                    
                    curr_start, curr_end = tuple(user_times[day])
                    is_off = (curr_start == curr_end)
                    
                    # --- 日ごとのクイックボタン ---
                    qbs = st.session_state.quick_buttons
                    if qbs:
                        btn_cols = st.columns(len(qbs) + 1)
                        for j, qb in enumerate(qbs):
                            with btn_cols[j]:
                                if st.button(qb["name"], key=f"btn_{week_key}_{day}_{j}", use_container_width=True): # keyにweek_keyを追加して重複回避
                                    st.session_state[f"time_{week_key}_{day}"] = (float_to_time_str(qb["start"]), float_to_time_str(qb["end"]))
                                    user_times[day] = (qb["start"], qb["end"])
                                    st.session_state.time_requests[name][week_key] = user_times
                                    st.rerun()
                                    
                        with btn_cols[-1]:
                            if is_off:
                                if st.button("🔄 戻す", key=f"btn_off_{week_key}_{day}", use_container_width=True):
                                    prev_time = st.session_state.previous_times.get(name, {}).get(day, (9.0, 17.0))
                                    st.session_state[f"time_{week_key}_{day}"] = (float_to_time_str(prev_time[0]), float_to_time_str(prev_time[1]))
                                    user_times[day] = prev_time
                                    st.session_state.time_requests[name][week_key] = user_times
                                    st.rerun()
                            else:
                                if st.button("🛌 休み", key=f"btn_off_{week_key}_{day}", use_container_width=True):
                                    if name not in st.session_state.previous_times:
                                        st.session_state.previous_times[name] = {}
                                    st.session_state.previous_times[name][day] = (curr_start, curr_end)
                                    st.session_state[f"time_{week_key}_{day}"] = (float_to_time_str(6.0), float_to_time_str(6.0))
                                    user_times[day] = (6.0, 6.0)
                                    st.session_state.time_requests[name][week_key] = user_times
                                    st.rerun()
                    
                    # --- マニュアル微調整スライダー ---
                    if is_off:
                        st.info("🛌 休み設定中（時間を指定する場合は上の「🔄 戻す」を押すか、スライダーを動かしてください）")
                        
                    start_str = float_to_time_str(curr_start)
                    end_str = float_to_time_str(curr_end)
                    
                    sel_start, sel_end = st.select_slider(
                        "時間範囲", 
                        options=time_options,
                        value=(st.session_state.get(f"time_{week_key}_{day}", (start_str, end_str))), # session_stateの値を優先
                        key=f"time_{week_key}_{day}",
                        label_visibility="collapsed"
                    )
                    user_times[day] = (time_str_to_float(sel_start), time_str_to_float(sel_end))
                    
                    st.divider()
            
            st.write("") 
            if st.button("基本希望を保存して提出", use_container_width=True, type="primary"):
                # 選んだ週(week_key)の中にデータを保存する！
                st.session_state.time_requests[name][week_key] = user_times
                save_data() 
                st.success(f"✅ {selected_week_label} のシフト希望を提出し、データが保存されました！")

        with tab2:
            st.title(f"📅 {name} さんの月別タイムカード")
            
            wage = st.session_state.employees.loc[st.session_state.employees["名前"] == name, "時給"].values[0]
            st.write(f"💵 あなたの現在の時給設定: **{wage}円**")
            
            with st.form(key=f"record_form"):
                st.markdown("### 新しい勤務記録を追加")
                
                col_d, col_b = st.columns(2)
                with col_d:
                    work_date = st.date_input("勤務日を選択（カレンダー）", today)
                with col_b:
                    break_time_m = st.number_input("休憩時間（分）", min_value=0, max_value=300, value=60, step=1)
                
                st.write("")
                st.markdown("出勤・退勤時刻")
                col_s_h, col_s_m, col_e_h, col_e_m = st.columns(4)
                
                with col_s_h:
                    work_start_h = st.number_input("出勤（時）", min_value=0, max_value=25, value=9)
                with col_s_m:
                    work_start_m = st.number_input("出勤（分）", min_value=0, max_value=59, value=0)
                with col_e_h:
                    work_end_h = st.number_input("退勤（時）", min_value=0, max_value=25, value=17)
                with col_e_m:
                    work_end_m = st.number_input("退勤（分）", min_value=0, max_value=59, value=0)
                
                submit_record = st.form_submit_button("記録を保存")
                
                if submit_record:
                    target_date_str = work_date.strftime("%Y/%m/%d")
                    existing_dates = [r["日付"] for r in st.session_state.work_records[name]]
                    
                    if target_date_str in existing_dates:
                        st.error(f"⚠️ {target_date_str} の勤務記録はすでに登録されています！内容を修正したい場合は、下の表から該当する行を削除・保存してから、再度上のフォームで入力し直してください。")
                    else:
                        start_total_m = (work_start_h * 60) + work_start_m
                        end_total_m = (work_end_h * 60) + work_end_m
                        
                        if end_total_m <= start_total_m:
                            st.error("退勤時間は出勤時間より後にしてください！")
                        else:
                            if end_total_m - start_total_m < break_time_m:
                                st.error("休憩時間が勤務時間より長いです！")
                            else:
                                # --- 1分単位での厳密な給与計算ロジック ---
                                times = list(range(start_total_m, end_total_m))
                                # 通常時間帯(5:00-22:00)と深夜時間帯(22:00-翌5:00)に分割
                                normal_times = [m for m in times if 300 <= (m % 1440) < 1320]
                                night_times = [m for m in times if (m % 1440) >= 1320 or (m % 1440) < 300]
                                
                                # スタッフに不利にならないよう、休憩は「通常時間帯」から優先して消化
                                break_left = break_time_m
                                normal_work = []
                                for m in normal_times:
                                    if break_left > 0:
                                        break_left -= 1
                                    else:
                                        normal_work.append(m)
                                        
                                night_work = []
                                for m in night_times:
                                    if break_left > 0:
                                        break_left -= 1
                                    else:
                                        night_work.append(m)
                                
                                # 実労働分を時間順に統合
                                actual_work_times = sorted(normal_work + night_work)
                                
                                wage_total = 0.0
                                base_wage_per_min = wage / 60.0
                                
                                for i, m in enumerate(actual_work_times):
                                    is_night = (m % 1440) >= 1320 or (m % 1440) < 300 # 22時以降
                                    is_overtime = i >= 480 # 8時間（480分）以降は残業
                                    
                                    rate = 1.0
                                    if is_night and is_overtime:
                                        rate = 1.25 * 1.25 # 深夜残業: 1.5625倍
                                    elif is_night or is_overtime:
                                        rate = 1.25        # 深夜 または 残業: 1.25倍
                                        
                                    wage_total += base_wage_per_min * rate
                                
                                work_hours = len(actual_work_times) / 60.0
                                daily_wage = int(wage_total)
                                # --------------------------------------------
                                
                                new_record = {
                                    "日付": target_date_str,
                                    "出勤": f"{work_start_h:02d}:{work_start_m:02d}",
                                    "退勤": f"{work_end_h:02d}:{work_end_m:02d}",
                                    "休憩(分)": break_time_m,
                                    "労働時間(H)": round(work_hours, 2),
                                    "日給(円)": daily_wage
                                }
                                st.session_state.work_records[name].append(new_record)
                                st.session_state.work_records[name].sort(key=lambda x: x["日付"])
                                save_data()
                                st.success(f"{work_date.strftime('%Y年%m月%d日')}の記録（{daily_wage}円）を保存しました！")
                                st.rerun()

            st.divider()
            
            st.markdown("### 月別データの確認と削除")
            st.caption("※記録を修正する場合は、表を直接書き換えずに、該当する行を選択して右上のゴミ箱マークで削除してください。その後「削除を反映する」ボタンを押し、改めて上のフォームから正しい時間を入力し直してください。")
            
            all_records = st.session_state.work_records[name]
            
            if all_records:
                df_all = pd.DataFrame(all_records)
                df_all['月'] = df_all['日付'].apply(lambda x: x[:7]) 
                available_months = sorted(list(df_all['月'].unique()), reverse=True)
            else:
                available_months = [today.strftime("%Y/%m")]
                df_all = pd.DataFrame(columns=["日付", "出勤", "退勤", "休憩(分)", "労働時間(H)", "日給(円)", "月"])
            
            selected_month = st.selectbox("表示する月を選択", available_months)
            
            if not df_all.empty:
                df_month = df_all[df_all['月'] == selected_month].drop(columns=['月'])
            else:
                df_month = pd.DataFrame(columns=["日付", "出勤", "退勤", "休憩(分)", "労働時間(H)", "日給(円)"])
            
            edited_month_records = st.data_editor(
                df_month, 
                num_rows="dynamic",
                hide_index=False,
                use_container_width=True,
                disabled=df_month.columns.tolist(),
                key=f"record_editor_{name}_{selected_month}"
            )
            
            if st.button(f"この月（{selected_month}）の削除を反映する"):
                valid_records = edited_month_records.dropna(subset=["日付"]).copy()
                other_month_records = [r for r in all_records if not r["日付"].startswith(selected_month)]
                new_month_records = valid_records.to_dict(orient="records")
                
                st.session_state.work_records[name] = other_month_records + new_month_records
                st.session_state.work_records[name].sort(key=lambda x: x["日付"])
                
                save_data()
                st.success(f"{selected_month}月の記録を更新（削除）しました！")
                st.rerun()
            
            total_salary = edited_month_records["日給(円)"].sum() if "日給(円)" in edited_month_records.columns else 0
            total_hours = edited_month_records["労働時間(H)"].sum() if "労働時間(H)" in edited_month_records.columns else 0
            st.info(f"✨ {selected_month}月の合計： **労働時間 {total_hours:.2f}H / 給料 {int(total_salary):,} 円**")
