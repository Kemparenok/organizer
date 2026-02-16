import sqlite3
import json
from datetime import datetime, timedelta, date
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey4children'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///organizer.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# -------------- МОДЕЛИ БАЗЫ ДАННЫХ ---------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    motivation = db.Column(db.String(256), default='')
    tasks = db.relationship('Task', backref='owner', lazy='dynamic')
    subscriptions = db.relationship('Subscription', backref='owner', lazy='dynamic')
    emergencystops = db.relationship('EmergencyStop', backref='owner', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    description = db.Column(db.String(200))
    complexity = db.Column(db.String(20))  # high/medium/low
    priority = db.Column(db.String(20), default='medium')
    estimated_minutes = db.Column(db.Integer)
    status = db.Column(db.String(20), default='pending')  # pending/completed/cancelled
    scheduled_time = db.Column(db.DateTime)
    clarification_asked = db.Column(db.Boolean, default=False)
    clarification_answer = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    plan_json = db.Column(db.Text)  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    active = db.Column(db.Boolean, default=False)
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    penalty_amount = db.Column(db.Float, default=0.0)
    confirmed_terms = db.Column(db.Boolean, default=False)
    confirmed_email = db.Column(db.Boolean, default=False)

class EmergencyStop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    stop_time = db.Column(db.DateTime, default=datetime.utcnow)
    reason = db.Column(db.String(200))
    resumed = db.Column(db.Boolean, default=False)

# --------------- ЗАГРУЗЧИК ПОЛЬЗОВАТЕЛЯ ---------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---------------
def estimate_complexity(desc):
    desc = desc.lower()
    high = ['сложн', 'трудн', 'анализ', 'отчёт', 'проект', 'диплом']
    low = ['купить', 'позвонить', 'убрать', 'помыть', 'забрать']
    if any(k in desc for k in high):
        return 'high'
    if any(k in desc for k in low):
        return 'low'
    return 'medium'

def need_clarification(desc, comp):
    if comp == 'medium' and len(desc.split()) > 3:
        return True
    return False

def build_schedule(tasks):
    schedule = []
    now = datetime.now()
    start_time = now.replace(hour=9, minute=0, second=0) if now.hour < 9 else now + timedelta(minutes=5)
    for task in tasks:
        if task.complexity == 'high':
            task.estimated_minutes = 90
        elif task.complexity == 'medium':
            task.estimated_minutes = 45
        else:
            task.estimated_minutes = 15

    tasks_sorted = sorted(tasks, key=lambda t: (t.complexity != 'high', t.complexity != 'medium'))
    current = start_time
    for task in tasks_sorted:
        work = task.estimated_minutes
        while work > 0:
            pomo = min(25 if task.complexity=='low' else 45, work)
            end = current + timedelta(minutes=pomo)
            schedule.append({
                'task_id': task.id,
                'desc': task.description,
                'start': current.strftime('%H:%M'),
                'end': end.strftime('%H:%M'),
                'type': 'work'
            })
            work -= pomo
            current = end
            if work > 0:
                break_end = current + timedelta(minutes=5)
                schedule.append({'type': 'break', 'start': current.strftime('%H:%M'), 'end': break_end.strftime('%H:%M')})
                current = break_end
        if task != tasks_sorted[-1]:
            current += timedelta(minutes=10)
    return schedule

# --------------- НОВЫЙ, НЕВЕРОЯТНО КРАСИВЫЙ ДИЗАЙН ---------------
def render_page(content_html, **context):
    base = '''
<!doctype html>
<html>
<head>
    <title>🌳 Лесной органайзер</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;800&display=swap');
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Montserrat', sans-serif;
            background: radial-gradient(circle at 10% 30%, #1c4e3d, #0a2f1f);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            position: relative;
            overflow-x: hidden;
        }
        /* Гигантские тени деревьев на фоне */
        body::before {
            content: "🌲🌳🌴🌿🍃🌾🌱";
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            font-size: 180px;
            color: rgba(255, 255, 255, 0.03);
            white-space: nowrap;
            pointer-events: none;
            transform: rotate(-10deg) scale(1.5);
            line-height: 1;
            z-index: 0;
        }
        .container {
            max-width: 1100px;
            width: 100%;
            background: rgba(10, 40, 20, 0.7);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-radius: 70px 70px 70px 70px;
            padding: 40px 50px;
            box-shadow: 0 30px 60px rgba(0, 20, 0, 0.8), inset 0 2px 5px rgba(255, 255, 200, 0.3);
            border: 3px solid #4c9e6a;
            position: relative;
            z-index: 2;
        }
        /* Декоративные лианы */
        .container::before {
            content: "🪴🌿🍃🌱";
            position: absolute;
            top: -20px;
            left: -20px;
            font-size: 60px;
            opacity: 0.4;
            transform: rotate(-15deg);
        }
        .container::after {
            content: "🌿🍂🌾";
            position: absolute;
            bottom: -30px;
            right: -30px;
            font-size: 80px;
            opacity: 0.3;
            transform: rotate(10deg);
        }
        .nav {
            display: flex;
            flex-wrap: wrap;
            gap: 18px;
            margin-bottom: 40px;
            justify-content: center;
        }
        .nav a {
            background: #1d4a2b;
            padding: 18px 28px;
            border-radius: 60px;
            text-decoration: none;
            color: #f0f7e0;
            font-weight: 700;
            font-size: 20px;
            letter-spacing: 1px;
            box-shadow: 0 10px 0 #0b2a15, 0 8px 20px rgba(0, 0, 0, 0.6);
            transition: all 0.15s ease;
            border: 2px solid #7fcb8f;
            display: inline-flex;
            align-items: center;
            gap: 15px;
            text-shadow: 2px 2px 0 #0a2a10;
            flex: 0 1 auto;
        }
        .nav a:hover {
            transform: translateY(-5px);
            box-shadow: 0 15px 0 #0b2a15, 0 15px 30px #00000080;
            background: #2b6b3b;
            border-color: #a4e0b0;
        }
        .nav a:active {
            transform: translateY(5px);
            box-shadow: 0 5px 0 #0b2a15, 0 8px 20px black;
        }
        h1, h2, h3 {
            color: #daf5da;
            text-shadow: 3px 3px 0 #1b4a2b, 0 0 15px #93e9a3;
            margin-bottom: 30px;
            font-weight: 800;
            font-size: 2.4rem;
            border-left: 12px solid #79c07a;
            padding-left: 30px;
            letter-spacing: -0.5px;
        }
        h2 {
            font-size: 2rem;
            border-left-width: 8px;
        }
        .flash {
            padding: 18px 30px;
            border-radius: 50px;
            margin-bottom: 30px;
            font-weight: 600;
            font-size: 1.2rem;
            border: 3px solid;
            box-shadow: 0 5px 0 #0a2f1a;
            backdrop-filter: blur(5px);
        }
        .flash.success {
            background: #27863c;
            color: #eaffd8;
            border-color: #b6f7b6;
        }
        .flash.error {
            background: #8b2c2c;
            color: #ffe0e0;
            border-color: #ff8888;
        }
        form {
            margin: 30px 0;
        }
        input[type="text"], input[type="password"], input[type="email"], input[type="number"] {
            width: 100%;
            max-width: 500px;
            padding: 20px 25px;
            margin: 15px 0;
            border: none;
            border-radius: 50px;
            background: #f4ffe4;
            font-size: 18px;
            box-shadow: inset 0 5px 10px #0a2f1a, 0 5px 0 #2c5a3a;
            transition: 0.2s;
            border: 2px solid #5fa86f;
        }
        input:focus {
            outline: none;
            box-shadow: inset 0 5px 10px #0a2f1a, 0 5px 0 #2c5a3a, 0 0 0 5px #a3d8a3;
            background: #ffffff;
        }
        button {
            background: #2e7d5a;
            border: none;
            padding: 18px 40px;
            border-radius: 60px;
            font-size: 22px;
            font-weight: 800;
            color: #f0ffe0;
            text-transform: uppercase;
            box-shadow: 0 12px 0 #144d2a, 0 10px 30px black;
            cursor: pointer;
            transition: 0.1s ease;
            border: 2px solid #9fdf9f;
            display: inline-flex;
            align-items: center;
            gap: 15px;
            margin: 10px 10px 0 0;
            letter-spacing: 1.5px;
        }
        button:hover {
            background: #3f9e6b;
            transform: translateY(-6px);
            box-shadow: 0 18px 0 #144d2a, 0 15px 40px black;
        }
        button:active {
            transform: translateY(6px);
            box-shadow: 0 6px 0 #144d2a, 0 10px 30px black;
        }
        ul {
            list-style: none;
        }
        li {
            background: #1b3d27;
            margin: 20px 0;
            padding: 25px 35px;
            border-radius: 60px;
            box-shadow: 0 10px 0 #0a2819, 0 10px 30px black;
            border: 2px solid #69a87c;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            transition: 0.2s;
            backdrop-filter: blur(5px);
            color: #ebffe3;
            font-size: 1.2rem;
        }
        li:hover {
            transform: scale(1.02);
            border-color: #bef5be;
            box-shadow: 0 12px 0 #0a2819, 0 20px 40px black;
        }
        li b {
            color: #d0ffc0;
            font-size: 1.3rem;
            text-shadow: 0 2px 0 #0f401f;
        }
        table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0 20px;
        }
        th {
            text-align: left;
            padding: 18px 25px;
            background: #22663a;
            color: #eeffee;
            font-size: 1.3rem;
            border-radius: 50px 50px 20px 20px;
            border: 2px solid #8fcf8f;
            box-shadow: 0 5px 0 #0a2f1a;
        }
        td {
            background: #1b452a;
            padding: 20px 30px;
            border-radius: 50px;
            border: 2px solid #7bb87b;
            color: #e3ffe3;
            font-size: 1.2rem;
            box-shadow: 0 8px 0 #0a2819;
        }
        hr {
            border: 3px dashed #5ba36b;
            margin: 40px 0;
        }
        .footer {
            margin-top: 60px;
            text-align: center;
            color: #abeba5;
            font-size: 1.5rem;
            text-shadow: 2px 2px 0 #154d21;
        }
        .footer span {
            font-size: 3.5rem;
            display: block;
            filter: drop-shadow(0 10px 5px #1a3a1a);
        }
        a {
            color: #bef5be;
            text-decoration: underline wavy #6fa86f;
            font-weight: 600;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="nav">
        {% if current_user.is_authenticated %}
            <a href="{{ url_for('index') }}">🌲 Главная</a>
            <a href="{{ url_for('tasks') }}">🌿 Задачи</a>
            <a href="{{ url_for('schedule') }}">🍃 Расписание</a>
            <a href="{{ url_for('motivation') }}">🌱 Мотивация</a>
            <a href="{{ url_for('subscription') }}">🌳 Подписка</a>
            <a href="{{ url_for('emergency') }}">🍂 Форс-мажор</a>
            <a href="{{ url_for('logout') }}">🌾 Выйти</a>
        {% else %}
            <a href="{{ url_for('login') }}">🌲 Вход</a>
            <a href="{{ url_for('register') }}">🌿 Регистрация</a>
        {% endif %}
    </div>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="flash {{ category }}">{{ message }} 🪴</div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    {{ content|safe }}
    <div class="footer">
        <span>🌳🌴🌿</span>
        Лесной органайзер — расти большим 🌱
    </div>
</div>
</body>
</html>
    '''
    # Подставляем контент
    full_html = base.replace('{{ content|safe }}', '{{ content|safe }}')  # для корректной работы render_template_string
    context['content'] = content_html
    return render_template_string(full_html, **context)

# --------------- МАРШРУТЫ (БЕЗ ИЗМЕНЕНИЙ, КРОМЕ ДИЗАЙНА) ---------------
@app.route('/')
def index():
    if current_user.is_authenticated:
        tasks_count = Task.query.filter_by(user_id=current_user.id, status='pending').count()
        content = f'''
<h1>🌳 Добро пожаловать в лес, {current_user.username}!</h1>
<p style="font-size: 1.8rem; color: #caf7ca;">Твоя мотивация: <i style="color:#f5ffa3;">{current_user.motivation or 'не указана'}</i></p>
<p style="font-size: 2rem;">Сегодня <span style="background:#2e7d32; padding:10px 30px; border-radius:60px;">{tasks_count}</span> задач ждут.</p>
<div style="font-size: 5rem; text-align: center; margin: 40px 0;">🌲🌴🌱</div>
        '''
        return render_page(content, current_user=current_user)
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Имя уже занято', 'error')
            return redirect(url_for('register'))
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Регистрация успешна, войди в лес', 'success')
        return redirect(url_for('login'))
    content = '''
<h2>🌿 Регистрация</h2>
<form method="post">
    <input type="text" name="username" placeholder="Имя" required><br>
    <input type="email" name="email" placeholder="Email" required><br>
    <input type="password" name="password" placeholder="Пароль" required><br>
    <button type="submit">Стать частью леса 🌱</button>
</form>
    '''
    return render_page(content)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Неверное имя или пароль', 'error')
    content = '''
<h2>🌲 Вход в лес</h2>
<form method="post">
    <input type="text" name="username" placeholder="Имя" required><br>
    <input type="password" name="password" placeholder="Пароль" required><br>
    <button type="submit">Войти 🌳</button>
</form>
    '''
    return render_page(content)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/tasks')
@login_required
def tasks():
    tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.created_at.desc()).all()
    tasks_html = ''
    for task in tasks:
        tasks_html += f'<li><b>{task.description}</b> (сложность: {task.complexity})'
        if task.clarification_asked:
            tasks_html += f' <br><small>🌿 <a href="{url_for("clarify", task_id=task.id)}">уточнить</a></small>'
        if task.status == 'pending':
            tasks_html += f'''
                <form method="post" action="{url_for('complete_task', task_id=task.id)}" style="display:inline;">
                    <button type="submit" style="padding:12px 25px;">✅ Выполнено</button>
                </form>
            '''
        else:
            tasks_html += ' ✔️'
        tasks_html += '</li>'
    if not tasks:
        tasks_html = '<li>🌱 Пока нет задач. Добавь что-нибудь полезное!</li>'
    content = f'''
<h2>📋 Мои задачи</h2>
<form method="post" action="{url_for('add_task')}">
    <input type="text" name="description" placeholder="Новая задача, например: Полить цветы" size="50" required>
    <button type="submit">➕ Добавить задачу</button>
</form>
<hr>
<ul>
{tasks_html}
</ul>
    '''
    return render_page(content)

@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    desc = request.form['description']
    comp = estimate_complexity(desc)
    task = Task(user_id=current_user.id, description=desc, complexity=comp, status='pending')
    if need_clarification(desc, comp):
        task.clarification_asked = True
    db.session.add(task)
    db.session.commit()
    flash('Задача добавлена 🌿', 'success')
    return redirect(url_for('tasks'))

@app.route('/clarify/<int:task_id>', methods=['GET', 'POST'])
@login_required
def clarify(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id != current_user.id:
        flash('Это не ваша задача', 'error')
        return redirect(url_for('tasks'))
    if request.method == 'POST':
        answer = request.form['answer']
        if answer == 'deep':
            task.complexity = 'high'
        else:
            task.complexity = 'low'
        task.clarification_asked = False
        task.clarification_answer = answer
        db.session.commit()
        flash('Сложность уточнена 🌻', 'success')
        return redirect(url_for('tasks'))
    content = f'''
<h2>🌱 Уточнение сложности</h2>
<p style="font-size:1.5rem;">Задача: <b>{task.description}</b></p>
<p>Система оценила сложность как <b>{task.complexity}</b>, помоги ей стать точнее.</p>
<form method="post">
    <p>Эта задача требует глубокого погружения или она тебе хорошо знакома?</p>
    <label><input type="radio" name="answer" value="deep" required> 🧠 Глубокое погружение (сложная)</label><br>
    <label><input type="radio" name="answer" value="simple"> 🌿 Знакомая/простая</label><br>
    <button type="submit">Подтвердить</button>
</form>
    '''
    return render_page(content)

@app.route('/complete/<int:task_id>', methods=['POST'])
@login_required
def complete_task(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id == current_user.id and task.status == 'pending':
        task.status = 'completed'
        db.session.commit()
        flash('Задача выполнена, отлично! 🌸', 'success')
    else:
        flash('Ошибка', 'error')
    return redirect(url_for('tasks'))

@app.route('/schedule')
@login_required
def schedule():
    sched = Schedule.query.filter_by(user_id=current_user.id, date=date.today()).first()
    if sched:
        plan = json.loads(sched.plan_json)
        table_rows = ''
        for item in plan:
            table_rows += f'<tr><td>{item["start"]} – {item["end"]}</td><td>{item.get("desc","-")}</td><td>{item["type"]}</td></tr>'
        schedule_table = f'''
        <table>
        <tr><th>Время</th><th>Задача</th><th>Тип</th></tr>
        {table_rows}
        </table>
        <form method="post" action="{url_for('rebuild_schedule')}">
            <button type="submit">🔄 Перестроить расписание</button>
        </form>
        '''
    else:
        schedule_table = f'<p>🍃 Расписание ещё не построено. <a href="{url_for("rebuild_schedule")}">Построить</a></p>'
    content = f'<h2>⏰ Расписание на сегодня</h2>{schedule_table}'
    return render_page(content)

@app.route('/rebuild_schedule', methods=['POST','GET'])
@login_required
def rebuild_schedule():
    tasks = Task.query.filter_by(user_id=current_user.id, status='pending').all()
    if not tasks:
        flash('Нет задач для планирования', 'error')
        return redirect(url_for('tasks'))
    plan = build_schedule(tasks)
    sched = Schedule.query.filter_by(user_id=current_user.id, date=date.today()).first()
    if sched:
        sched.plan_json = json.dumps(plan, ensure_ascii=False)
    else:
        sched = Schedule(user_id=current_user.id, date=date.today(), plan_json=json.dumps(plan, ensure_ascii=False))
        db.session.add(sched)
    db.session.commit()
    flash('Расписание построено! Следуй плану 🌱', 'success')
    return redirect(url_for('schedule'))

@app.route('/motivation', methods=['GET','POST'])
@login_required
def motivation():
    if request.method == 'POST':
        current_user.motivation = request.form['motivation']
        db.session.commit()
        flash('Мотивация сохранена', 'success')
        return redirect(url_for('index'))
    content = f'''
<h2>💚 Моя мотивация</h2>
<form method="post">
    <input type="text" name="motivation" value="{current_user.motivation}" size="60" placeholder="Например: Ради детей, семьи, себя...">
    <button type="submit">Сохранить 🌻</button>
</form>
<p>Эта фраза будет напоминать, зачем ты всё это делаешь.</p>
    '''
    return render_page(content)

@app.route('/subscription')
@login_required
def subscription():
    sub = Subscription.query.filter_by(user_id=current_user.id, active=True).first()
    active = sub is not None
    penalty = sub.penalty_amount if sub else 0
    if active:
        content = f'''
<h2>💰 Подписка с финансовым стимулом</h2>
<p>Статус: <b style="color:#a5f7a5;">🌿 Активна</b></p>
<p>Штраф за пропуск задачи: {penalty} руб.</p>
<form method="post" action="{url_for('deactivate_subscription')}">
    <button type="submit">🚫 Деактивировать</button>
</form>
        '''
    else:
        content = '''
<h2>💰 Подписка с финансовым стимулом</h2>
<p>Подписка не активна. Активируй, чтобы деньги мотивировали!</p>
<form method="post" action="''' + url_for('activate_subscription') + '''">
    <input type="number" name="penalty" placeholder="Сумма штрафа (руб)" value="100" required><br>
    <label><input type="checkbox" name="terms" required> 🌱 Я понимаю, что при невыполнении задач с меня спишут деньги</label><br>
    <label><input type="checkbox" name="email_confirm" required> 🌼 Я подтверждаю свою электронную почту (имитация)</label><br>
    <button type="submit">🌿 Активировать</button>
</form>
        '''
    return render_page(content)

@app.route('/activate_subscription', methods=['POST'])
@login_required
def activate_subscription():
    if not request.form.get('terms') or not request.form.get('email_confirm'):
        flash('Необходимо подтвердить условия', 'error')
        return redirect(url_for('subscription'))
    sub = Subscription.query.filter_by(user_id=current_user.id).first()
    if sub:
        sub.active = True
        sub.start_date = datetime.utcnow()
        sub.end_date = None
        sub.penalty_amount = float(request.form.get('penalty', 100))
        sub.confirmed_terms = True
        sub.confirmed_email = True
    else:
        sub = Subscription(
            user_id=current_user.id,
            active=True,
            start_date=datetime.utcnow(),
            penalty_amount=float(request.form.get('penalty', 100)),
            confirmed_terms=True,
            confirmed_email=True
        )
        db.session.add(sub)
    db.session.commit()
    flash('Подписка активирована. Деньги любят дисциплину! 🌱', 'success')
    return redirect(url_for('subscription'))

@app.route('/deactivate_subscription', methods=['POST'])
@login_required
def deactivate_subscription():
    sub = Subscription.query.filter_by(user_id=current_user.id, active=True).first()
    if sub:
        sub.active = False
        sub.end_date = datetime.utcnow()
        db.session.commit()
        flash('Подписка деактивирована', 'success')
    return redirect(url_for('subscription'))

@app.route('/emergency')
@login_required
def emergency():
    active = EmergencyStop.query.filter_by(user_id=current_user.id, resumed=False).first()
    if active:
        content = '''
<h2>🚨 Экстренная остановка</h2>
<p style="color: #ffb7b7;">⚡ Режим форс-мажора активирован. Все таймеры и штрафы приостановлены.</p>
<form method="post" action="''' + url_for('emergency_resume') + '''">
    <button type="submit">🌿 Возобновить работу</button>
</form>
        '''
    else:
        content = '''
<h2>🚨 Экстренная остановка</h2>
<p>Если случилось непредвиденное, нажми кнопку ниже. Это отменит все штрафы на сегодня и приостановит планирование.</p>
<form method="post" action="''' + url_for('emergency_stop') + '''">
    <input type="text" name="reason" placeholder="Причина (необязательно)">
    <button type="submit">🌿 Активировать форс-мажор</button>
</form>
        '''
    return render_page(content)

@app.route('/emergency_stop', methods=['POST'])
@login_required
def emergency_stop():
    reason = request.form.get('reason', '')
    stop = EmergencyStop(user_id=current_user.id, reason=reason)
    db.session.add(stop)
    db.session.commit()
    flash('Экстренная остановка активирована. Все штрафы отменены. 🌿', 'success')
    return redirect(url_for('emergency'))

@app.route('/emergency_resume', methods=['POST'])
@login_required
def emergency_resume():
    stop = EmergencyStop.query.filter_by(user_id=current_user.id, resumed=False).first()
    if stop:
        stop.resumed = True
        db.session.commit()
        flash('Работа возобновлена. Можешь перепланировать задачи.', 'success')
    return redirect(url_for('emergency'))

# --------------- ЗАПУСК ---------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)