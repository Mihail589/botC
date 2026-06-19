import os
import sys
import time
import subprocess
import threading
from collections import deque
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)

# Путь к скрипту бота (измените под свой)
BOT_SCRIPT = "bot.py"
# Интервал проверки статуса (секунды)
CHECK_INTERVAL = 5
# Максимальное количество строк лога
MAX_LOG_LINES = 500

# Глобальные переменные
bot_process = None
process_lock = threading.Lock()
monitoring_thread = None
stop_monitoring = threading.Event()
logs = deque(maxlen=MAX_LOG_LINES)

def add_log(message, level="INFO"):
    """Добавляет запись в лог с временной меткой."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Очищаем строку от лишних символов
    message = message.rstrip('\n\r')
    logs.append(f"[{timestamp}] [{level}] {message}")

def start_bot_process():
    """Запускает бота как дочерний процесс и начинает читать его вывод."""
    global bot_process
    with process_lock:
        if bot_process is not None and bot_process.poll() is None:
            add_log("Попытка запуска, но бот уже запущен", "WARNING")
            return False
        try:
            # Ключевые изменения для захвата print():
            # 1. PYTHONUNBUFFERED=1 - отключает буферизацию Python
            # 2. universal_newlines=True - текстовый режим
            # 3. bufsize=1 - построчная буферизация
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            
            bot_process = subprocess.Popen(
                [sys.executable, BOT_SCRIPT],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
                universal_newlines=True
            )
            add_log(f"Бот запущен (PID {bot_process.pid})", "INFO")
            
            # Запускаем потоки для чтения вывода с немедленной обработкой
            threading.Thread(target=read_output, args=(bot_process.stdout, "STDOUT"), daemon=True).start()
            threading.Thread(target=read_output, args=(bot_process.stderr, "STDERR"), daemon=True).start()
            return True
        except Exception as e:
            add_log(f"Ошибка запуска бота: {e}", "ERROR")
            return False

def read_output(stream, source):
    """Читает строки из потока и добавляет в лог с минимальной задержкой."""
    try:
        while True:
            line = stream.readline()
            if not line:
                break
            if line:
                add_log(line.rstrip('\n\r'), source)
    except Exception as e:
        add_log(f"Ошибка чтения {source}: {e}", "ERROR")
    finally:
        stream.close()

def stop_bot_process():
    """Останавливает бота (если запущен)."""
    global bot_process
    with process_lock:
        if bot_process is None or bot_process.poll() is not None:
            add_log("Попытка остановки, но бот не запущен", "WARNING")
            bot_process = None
            return False
        try:
            add_log(f"Останавливаем бота (PID {bot_process.pid})...", "INFO")
            bot_process.terminate()
            bot_process.wait(timeout=5)
            add_log("Бот остановлен (terminate)", "INFO")
        except subprocess.TimeoutExpired:
            bot_process.kill()
            add_log("Бот остановлен принудительно (kill)", "WARNING")
        bot_process = None
        return True

def restart_bot():
    """Перезапускает бота."""
    add_log("Начинаем перезапуск бота...", "INFO")
    stop_bot_process()
    time.sleep(1)
    return start_bot_process()

def get_bot_status():
    """Возвращает статус бота: running, stopped, error."""
    with process_lock:
        if bot_process is None:
            return "stopped"
        poll = bot_process.poll()
        if poll is None:
            return "running"
        else:
            if poll != 0:
                add_log(f"Бот завершился с кодом {poll}", "ERROR")
            return "error"

def monitor_bot():
    """Фоновый поток: проверяет статус и автоматически перезапускает при ошибке."""
    while not stop_monitoring.is_set():
        status = get_bot_status()
        if status == "error":
            add_log("Обнаружена ошибка, автоматический перезапуск...", "ERROR")
            restart_bot()
        time.sleep(CHECK_INTERVAL)

@app.route('/')
def index():
    """Главная страница с логом и кнопками управления."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Мониторинг бота</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 30px; }
            .status { font-size: 24px; margin: 20px 0; }
            .running { color: green; }
            .stopped { color: gray; }
            .error { color: red; }
            button { padding: 10px 20px; margin: 5px; cursor: pointer; font-size: 14px; }
            button:hover { opacity: 0.8; }
            #log-container {
                border: 1px solid #ccc;
                background: #1e1e1e;
                color: #d4d4d4;
                height: 500px;
                overflow-y: auto;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
                margin-top: 20px;
                border-radius: 5px;
            }
            .log-line { 
                padding: 2px 0;
                border-bottom: 1px solid #2a2a2a;
                white-space: pre-wrap;
                word-break: break-all;
            }
            .INFO { color: #d4d4d4; }
            .WARNING { color: #ffcc00; }
            .ERROR { color: #ff4444; }
            .STDOUT { color: #4ec9b0; }
            .STDERR { color: #ff6b6b; }
            .controls { margin-bottom: 20px; }
            .btn-start { background: #4CAF50; color: white; border: none; }
            .btn-stop { background: #f44336; color: white; border: none; }
            .btn-restart { background: #ff9800; color: white; border: none; }
            .info { color: #666; margin-left: 20px; }
            .log-header { display: flex; justify-content: space-between; align-items: center; }
            .clear-btn { background: #555; color: white; border: none; padding: 5px 15px; cursor: pointer; border-radius: 3px; }
            .clear-btn:hover { background: #777; }
        </style>
        <script>
            function updateStatus() {
                fetch('/status')
                    .then(res => res.json())
                    .then(data => {
                        const el = document.getElementById('status-text');
                        const cls = document.getElementById('status-class');
                        const statusMap = {
                            'running': { text: 'Работает', class: 'running' },
                            'stopped': { text: 'Остановлен', class: 'stopped' },
                            'error': { text: 'Ошибка', class: 'error' }
                        };
                        const info = statusMap[data.status] || { text: 'Неизвестно', class: '' };
                        el.textContent = info.text;
                        cls.className = 'status ' + info.class;
                    });
            }
            function updateLogs() {
                fetch('/api/logs')
                    .then(res => res.json())
                    .then(data => {
                        const container = document.getElementById('log-container');
                        container.innerHTML = data.logs.map(line => {
                            // Определяем уровень для стилизации
                            let level = 'INFO';
                            if (line.includes('[ERROR]')) level = 'ERROR';
                            else if (line.includes('[WARNING]')) level = 'WARNING';
                            else if (line.includes('[STDOUT]')) level = 'STDOUT';
                            else if (line.includes('[STDERR]')) level = 'STDERR';
                            return `<div class="log-line ${level}">${escapeHtml(line)}</div>`;
                        }).join('');
                        // Автоскролл вниз
                        const isAtBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 5;
                        if (isAtBottom) {
                            container.scrollTop = container.scrollHeight;
                        }
                    });
            }
            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }
            function sendAction(url) {
                fetch(url)
                    .then(res => res.json())
                    .then(data => {
                        alert(data.message || data.status);
                        updateStatus();
                        updateLogs();
                    })
                    .catch(err => alert('Ошибка: ' + err));
            }
            function clearLogs() {
                if (confirm('Очистить лог?')) {
                    fetch('/api/logs/clear', { method: 'POST' })
                        .then(() => updateLogs());
                }
            }
            // Обновляем статус и логи каждую секунду (быстрее для отладки)
            setInterval(() => {
                updateStatus();
                updateLogs();
            }, 1000);
            // Первоначальная загрузка
            window.onload = function() {
                updateStatus();
                updateLogs();
            };
        </script>
    </head>
    <body>
        <h1>🤖 Мониторинг бота</h1>
        <div class="controls">
            <div class="status">
                Статус: <span id="status-class" class="status stopped"><span id="status-text">Загрузка...</span></span>
            </div>
            <button class="btn-start" onclick="sendAction('/start')">▶ Запустить</button>
            <button class="btn-stop" onclick="sendAction('/stop')">⏹ Остановить</button>
            <button class="btn-restart" onclick="sendAction('/restart')">🔄 Перезапустить</button>
            <span class="info">🔄 Автоперезапуск при ошибке: включён</span>
        </div>
        <div class="log-header">
            <h3>📋 Лог бота</h3>
            <button class="clear-btn" onclick="clearLogs()">Очистить</button>
        </div>
        <div id="log-container">
            <div class="log-line INFO">Ожидание логов...</div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/start')
def start():
    if start_bot_process():
        return jsonify({"status": "success", "message": "Бот запущен"})
    else:
        return jsonify({"status": "error", "message": "Бот уже запущен или ошибка"}), 400

@app.route('/stop')
def stop():
    if stop_bot_process():
        return jsonify({"status": "success", "message": "Бот остановлен"})
    else:
        return jsonify({"status": "error", "message": "Бот не запущен"}), 400

@app.route('/restart')
def restart():
    if restart_bot():
        return jsonify({"status": "success", "message": "Бот перезапущен"})
    else:
        return jsonify({"status": "error", "message": "Не удалось перезапустить"}), 500

@app.route('/status')
def status():
    return jsonify({"status": get_bot_status()})

@app.route('/api/logs')
def get_logs():
    """Возвращает последние строки лога."""
    return jsonify({"logs": list(logs)})

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    """Очищает лог."""
    logs.clear()
    add_log("Лог очищен", "INFO")
    return jsonify({"status": "success"})

def main():
    # Запускаем бота при старте
    start_bot_process()
    # Запускаем фоновый мониторинг
    global monitoring_thread
    monitoring_thread = threading.Thread(target=monitor_bot, daemon=True)
    monitoring_thread.start()
    # Запускаем Flask
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True, ssl_context=('/root/cert/ip/fullchain.pem', '/root/cert/ip/privkey.pem'))

if __name__ == '__main__':
    main()
