# app.py - Main Flask Application (No AI)
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
from bson import ObjectId
from dotenv import load_dotenv
import requests
import os

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config['MONGO_URI'] = os.getenv("MONGO_URI")
mongo = PyMongo(app)

# OpenWeatherMap API configuration
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
WEATHER_BASE_URL = 'https://api.openweathermap.org/data/2.5'


# -------------------- Authentication --------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        city = request.form.get('city', 'Your city')

        existing_user = mongo.db.users.find_one({
            '$or': [{'username': username}, {'email': email}]
        })

        if existing_user:
            flash('Username or email already exists', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        user_data = {
            'username': username,
            'email': email,
            'password': hashed_password,
            'city': city,
            'created_at': datetime.now(),
            'preferences': {
                'units': 'metric',
                'notifications': True
            }
        }

        result = mongo.db.users.insert_one(user_data)
        if result.inserted_id:
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = mongo.db.users.find_one({'username': username})

        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            session['city'] = user.get('city', 'London')

            mongo.db.login_history.insert_one({
                'user_id': user['_id'],
                'login_time': datetime.now(),
                'ip_address': request.remote_addr
            })

            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))


# -------------------- Dashboard --------------------
@app.route('/dashboard')
@login_required
def dashboard():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    city = user.get('city', 'London')

    current_weather = get_current_weather(city)
    forecast = get_weekly_forecast(city)

    if current_weather:
        mongo.db.weather_queries.insert_one({
            'user_id': ObjectId(session['user_id']),
            'city': city,
            'query_time': datetime.now(),
            'weather_data': current_weather,
            'forecast': forecast
        })

    return render_template(
        'dashboard.html',
        user=user,
        current_weather=current_weather,
        forecast=forecast
    )


@app.route('/update_city', methods=['POST'])
@login_required
def update_city():
    city = request.form.get('city')
    if city:
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$set': {'city': city}}
        )
        session['city'] = city
        flash(f'City updated to {city}', 'success')
    return redirect(url_for('dashboard'))


@app.route('/weather_history')
@login_required
def weather_history():
    history = mongo.db.weather_queries.find({
        'user_id': ObjectId(session['user_id'])
    }).sort('query_time', -1).limit(20)
    return render_template('history.html', history=list(history))


@app.route('/api/weather/<city>')
@login_required
def api_weather(city):
    current_weather = get_current_weather(city)
    forecast = get_weekly_forecast(city)
    return jsonify({'current': current_weather, 'forecast': forecast})


# -------------------- Weather Functions --------------------
def get_current_weather(city):
    try:
        url = f"{WEATHER_BASE_URL}/weather"
        params = {'q': city, 'appid': WEATHER_API_KEY, 'units': 'metric'}
        response = requests.get(url, params=params)

        if response.status_code == 200:
            data = response.json()
            return {
                'city': data['name'],
                'country': data['sys']['country'],
                'temperature': round(data['main']['temp']),
                'feels_like': round(data['main']['feels_like']),
                'description': data['weather'][0]['description'].capitalize(),
                'icon': data['weather'][0]['icon'],
                'humidity': data['main']['humidity'],
                'pressure': data['main']['pressure'],
                'wind_speed': data['wind']['speed'],
                'timestamp': datetime.now()
            }
    except Exception as e:
        print(f"Error fetching weather: {e}")
    return None


def get_weekly_forecast(city):
    try:
        url = f"{WEATHER_BASE_URL}/forecast"
        params = {'q': city, 'appid': WEATHER_API_KEY, 'units': 'metric', 'cnt': 56}
        response = requests.get(url, params=params)

        if response.status_code == 200:
            data = response.json()
            daily_forecast = {}

            for item in data['list']:
                date = datetime.fromtimestamp(item['dt']).date()
                date_str = date.strftime('%Y-%m-%d')

                if date_str not in daily_forecast:
                    daily_forecast[date_str] = {
                        'date': date.strftime('%A, %B %d'),
                        'temps': [],
                        'descriptions': [],
                        'humidity': [],
                        'wind': [],
                        'icon': item['weather'][0]['icon']
                    }

                daily_forecast[date_str]['temps'].append(item['main']['temp'])
                daily_forecast[date_str]['descriptions'].append(item['weather'][0]['description'])
                daily_forecast[date_str]['humidity'].append(item['main']['humidity'])
                daily_forecast[date_str]['wind'].append(item['wind']['speed'])

            forecast_list = []
            for date_str, day_data in list(daily_forecast.items())[:7]:
                forecast_list.append({
                    'date': day_data['date'],
                    'temp_max': round(max(day_data['temps'])),
                    'temp_min': round(min(day_data['temps'])),
                    'description': max(set(day_data['descriptions']), key=day_data['descriptions'].count),
                    'humidity': round(sum(day_data['humidity']) / len(day_data['humidity'])),
                    'wind_speed': round(sum(day_data['wind']) / len(day_data['wind']), 1),
                    'icon': day_data['icon']
                })

            return forecast_list
    except Exception as e:
        print(f"Error fetching forecast: {e}")
    return []


# -------------------- Profile --------------------
@app.route('/profile')
@login_required
def profile():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    query_count = mongo.db.weather_queries.count_documents({'user_id': ObjectId(session['user_id'])})
    return render_template('profile.html', user=user, query_count=query_count)


@app.route('/update_preferences', methods=['POST'])
@login_required
def update_preferences():
    units = request.form.get('units', 'metric')
    notifications = request.form.get('notifications') == 'on'

    mongo.db.users.update_one(
        {'_id': ObjectId(session['user_id'])},
        {'$set': {'preferences.units': units, 'preferences.notifications': notifications}}
    )

    flash('Preferences updated successfully', 'success')
    return redirect(url_for('profile'))


# -------------------- Run --------------------
if __name__ == "__main__":
    from waitress import serve
    import webbrowser

    host = "127.0.0.1"
    port = 5000
    url = f"http://{host}:{port}"

    print(f"\n🚀 This System is running at: {url}")
    print("🌐 Opening in your default web browser...\n")

    # Open the app in the default browser
    webbrowser.open(url)

    # Start the production server
    serve(app, host=host, port=port)


