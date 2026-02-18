import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
from datetime import datetime, timedelta
import qrcode
from io import BytesIO

# ใช้ template_folder='.' เพื่อให้หาไฟล์ html ในโฟลเดอร์เดียวกันเจอ
app = Flask(__name__, template_folder='.')
app.secret_key = 'yala_tech_booking_system'

# Config จำนวนคน
RESOURCE_LIMITS = {
    "สนามกีฬา": 12,
    "ห้องประชุม": 20,
    "ห้องแล็บคอมพิวเตอร์": 16
}

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS bookings 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user_name TEXT, 
                  booker_id TEXT, 
                  resource TEXT, 
                  participants TEXT,
                  start_time TEXT, end_time TEXT, 
                  status TEXT DEFAULT 'Pending')''')
    conn.commit()
    conn.close()

@app.route('/qrcode_img')
def qrcode_img():
    # บน Render ใช้ request.host_url ได้เลย ไม่ต้องหา IP เอง
    base_url = request.host_url
    img = qrcode.make(base_url)
    buf = BytesIO()
    img.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        bookings = conn.execute('SELECT * FROM bookings WHERE status = "Approved" ORDER BY start_time DESC').fetchall()
        conn.close()
    except:
        init_db()
        bookings = []
    return render_template('booking.html', bookings=bookings, resource_limits=RESOURCE_LIMITS)

@app.route('/book', methods=['POST'])
def book():
    user = request.form['user_name']
    booker_id = request.form['booker_id'].strip()
    resource = request.form['resource']
    participants_str = request.form['participants']
    friend_ids = [pid.strip() for pid in participants_str.split(',') if pid.strip()]
    all_team_ids = [booker_id] + friend_ids

    # 1. Capacity Check
    max_people = RESOURCE_LIMITS.get(resource, 10)
    if len(all_team_ids) > max_people:
        flash(f'ผิดพลาด: {resource} รองรับได้สูงสุด {max_people} คน (คุณใส่มา {len(all_team_ids)} คน)', 'error')
        return redirect(url_for('index'))

    # 2. Time Validation
    date = request.form['booking_date']
    time_start = request.form['start_time']
    time_end = request.form['end_time']
    start_str = f"{date}T{time_start}"
    end_str = f"{date}T{time_end}"
    
    try:
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
    except ValueError:
        flash('รูปแบบเวลาไม่ถูกต้อง', 'error')
        return redirect(url_for('index'))

    now = datetime.now()
    if start_dt < now:
        flash('ผิดพลาด: ไม่สามารถจองเวลาย้อนหลังได้!', 'error')
        return redirect(url_for('index'))
    if end_dt <= start_dt:
        flash('ผิดพลาด: เวลาสิ้นสุดต้องอยู่หลังเวลาเริ่ม!', 'error')
        return redirect(url_for('index'))
    
    # 3. Cooldown Check (2 Weeks)
    conn = get_db_connection()
    two_weeks_ago = (now - timedelta(days=14)).isoformat()
    recent_bookings = conn.execute('''
        SELECT booker_id, participants FROM bookings 
        WHERE status = 'Approved' AND start_time > ?
    ''', (two_weeks_ago,)).fetchall()
    conn.close()

    blocked_ids = []
    for booking in recent_bookings:
        past_team = [booking['booker_id']] + booking['participants'].split(',')
        for new_member in all_team_ids:
            if new_member in past_team:
                blocked_ids.append(new_member)
    
    if blocked_ids:
        blocked_ids = list(set(blocked_ids))
        flash(f'⛔ ไม่สามารถจองได้: รหัสนักศึกษา {", ".join(blocked_ids)} ติดสถานะ Cooldown 2 สัปดาห์', 'error')
        return redirect(url_for('index'))

    # 4. Conflict Check
    conn = get_db_connection()
    conflict = conn.execute('''SELECT * FROM bookings 
                             WHERE resource = ? AND status = 'Approved'
                             AND NOT (end_time <= ? OR start_time >= ?)''', 
                             (resource, start_str, end_str)).fetchone()
    
    if conflict:
        conn.close()
        flash(f'ขออภัย: "{resource}" ถูกจองแล้วในช่วงเวลานี้', 'error')
        return redirect(url_for('index'))

    # 5. Insert
    participants_db_str = ",".join(friend_ids)
    conn.execute('''INSERT INTO bookings 
                    (user_name, booker_id, resource, participants, start_time, end_time) 
                    VALUES (?, ?, ?, ?, ?, ?)''',
                 (user, booker_id, resource, participants_db_str, start_str, end_str))
    conn.commit()
    conn.close()
    flash('บันทึกการจองสำเร็จ! กรุณารอการอนุมัติ', 'success')
    return redirect(url_for('index'))

@app.route('/my_bookings', methods=['GET', 'POST'])
def my_bookings():
    conn = get_db_connection()
    bookings = []
    search_id = ""
    now_str = datetime.now().strftime('%Y-%m-%dT%H:%M')
    
    if request.method == 'POST':
        search_id = request.form['search_id'].strip()
        sql = "SELECT * FROM bookings WHERE (booker_id = ? OR participants LIKE ?) ORDER BY start_time DESC"
        bookings = conn.execute(sql, (search_id, '%' + search_id + '%')).fetchall()
    else:
        bookings = conn.execute("SELECT * FROM bookings WHERE start_time >= ? ORDER BY start_time ASC", (now_str,)).fetchall()
    
    conn.close()
    return render_template('my_bookings.html', bookings=bookings, search_id=search_id)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == '1234':
            session['logged_in'] = True
            return redirect(url_for('admin'))
    return render_template('login.html')

@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    conn = get_db_connection()
    bookings = conn.execute('SELECT * FROM bookings ORDER BY status DESC, start_time DESC').fetchall()
    total = conn.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'Pending'").fetchone()[0]
    approved = conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'Approved'").fetchone()[0]
    conn.close()
    
    return render_template('admin.html', bookings=bookings, total=total, pending=pending, approved=approved, server_url=request.host_url)

@app.route('/approve/<int:id>')
def approve(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    try:
        conn = get_db_connection()
        conn.execute("UPDATE bookings SET status = 'Approved' WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        flash('อนุมัติเรียบร้อย!', 'success')
    except Exception as e:
        flash(f'เกิดข้อผิดพลาด: {e}', 'error')
    return redirect(url_for('admin'))

@app.route('/delete/<int:id>')
def delete(id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    conn = get_db_connection()
    conn.execute('DELETE FROM bookings WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    # [จุดสำคัญ] รับค่า Port จาก Render (ถ้าไม่มีให้ใช้ 5000)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)