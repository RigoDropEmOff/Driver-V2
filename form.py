from flask import Flask, render_template, url_for, redirect, request, flash, jsonify, Response, session, send_from_directory
import requests
import os
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
import pytz
import base64
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import timedelta
import cloudinary
import cloudinary.uploader
import cloudinary.api


app = Flask(__name__)
app.secret_key = "my_secret_key"


LOCAL_TZ = pytz.timezone("America/Chicago")

#configure Database
#use Heroku's database_url if available, otherwise use SQLite
database_url = os.environ.get('DATABASE_URL', 'sqlite:///drivers.db')

# Heroku's PostgreSQL URL starts with 'postgres://', but SQLAlchemy expects 'postgresql://'
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)


app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

#configure file uploads
app.config['UPLOAD_FOLDER'] = 'static/uploads'
db = SQLAlchemy(app)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

#configure cloudinary for cloud image storage
cloudinary.config(
    cloud_name = "duu3rjz8f",
    api_key = "361137226743648",
    api_secret= "93RyNOaqDgZ-Jsq158J8WvQysj4"
)

#SMTP2Go API Parameters
SMTP2GO_API_URL = "https://api.smtp2go.com/v3/email/send"
SMTP2GO_API_KEY = "api-43E83469CC704967918416A4701A050C"  # Replace with your SMTP2Go API key
SENDER_EMAIL = 'receptionist@royalexpressinc.com'
DEFAULT_DEPARTMENT_EMAIL = 'hr_TEST_@royalexpressinc.com'  # Default HR email

#Allowed File Extensions
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

#database model
class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    provider_name = db.Column(db.String(100), nullable=False)
    truck_license = db.Column(db.String(50), nullable=False)
    card_id = db.Column(db.String(50), nullable=False)
    purpose_of_visit = db.Column(db.String(100), nullable=False)
    point_of_contact = db.Column(db.String(100), nullable=False)
    check_in_time = db.Column(db.DateTime, default=lambda: datetime.now(pytz.timezone('America/Chicago')).replace(microsecond=0))
    check_out_time = db.Column(db.DateTime, nullable=True)
    photo_path = db.Column(db.String(255), nullable=True)
    plate_photo_path = db.Column(db.String(255), nullable=True)

    # Add a unique constraint that only applies to active drivers
    __table_args__ = (
        db.UniqueConstraint('card_id', 'check_out_time', 
                           name='unique_active_card',
                           sqlite_on_conflict='IGNORE'),
    )

    def __repr__(self):
        return f"Driver('{self.name}', '{self.provider_name}', '{self.card_id}')"

def save_photo(photo_data, identifier, folder_name='driver_license'):
    if not photo_data:
        print("No photo data provided.")
        return None
    
    # Create uploads directory if it doesn't exist
    upload_dir = os.path.join(app.static_folder, 'uploads')
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    
    # Extract image data from base64 string
    try:
        print(" Decoding Base64 image data....")

        #exctract base64 data
        if ',' in photo_data:
            base64_data = photo_data.split(',')[1]
        else:
            base64_data = photo_data
        
        print("Base64 data extracted. Decoding...")  # Debugging print
        
        image_data = base64.b64decode(base64_data)

        #create url-friendly filename without spaces or special characters
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        #Replace spaces with underscores and remove special characters
        safe_identifier = "".join(c for c in identifier if c.isalnum() or c in "_-").replace(" ", "_")
        filename = f"{safe_identifier}_{timestamp}.jpg"
        
        #upload image to cloudinary
        upload_result = cloudinary.uploader.upload(
            f"data:image/jpeg;base64,{base64_data}",
            public_id = f"{folder_name}/{filename}",
            folder = "driver_app",
            upload_preset="Royal-30days",
            invalidate=True,
            invalidate_after=2592000  # 30 days in seconds
        )
        
        print(f"Image uploaded to Cloudinary: {upload_result['secure_url']}")

        #return the Cloudinary URL
        return upload_result['secure_url']
    

    
    except Exception as e:
        print(f"Error saving photo: {e}")
        return None



@app.route("/")
def index():
    return redirect(url_for("drivers"))


# Driver Management Route
@app.route("/drivers", methods=["GET", "POST"])
def drivers():
    print(">>Route Accessed:", request.method)

    if request.method == "POST":
        # Detect if request is an AJAX request
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        
        # Get form data
        driver_name = request.form.get("driver_name")
        provider_name = request.form.get("provider_name")
        truck_license = request.form.get("truck_license")
        card_id = request.form.get("card_id")
        purpose_of_visit = request.form.get("purpose_of_visit")
        point_of_contact = request.form.get("point_of_contact")
        photo_data = request.form.get("photo_data", "")
        plate_photo_data = request.form.get("plate_photo_data", "")

        # If photo is provided but no license number, use placeholder
        if photo_data and not truck_license:
            truck_license = "Photo Provided"

        # ✅ If purpose is "Security/Guardia", photos are not required
        if purpose_of_visit.lower() in ["security", "guardia"]:
            photo_data = None
            plate_photo_data = None

        # 📌 Debugging: Print received data
        print("\n📌 Received Form Data:")
        print(f"Driver Name: {driver_name}")
        print(f"Provider Name: {provider_name}")
        print(f"Truck License: {truck_license}")
        print(f"Card ID: {card_id}")
        print(f"Purpose of Visit: {purpose_of_visit}")
        print(f"Point of Contact: {point_of_contact}")
        print(f"Photo Data (first 100 chars): {photo_data[:100] if photo_data else 'No photo received'}")
        print(f"License Plate Photo Data (first 100 chars): {plate_photo_data[:100] if plate_photo_data else 'No photo received'}\n")

        # Validate required fields
        if not all([driver_name, provider_name, truck_license, card_id, purpose_of_visit, point_of_contact]):
            error_message = "All fields are required"
            print(f"❌ {error_message}\n")
            if is_ajax:
                return jsonify({"success": False, "message": error_message}), 400
            flash(error_message, "error")
            return redirect(url_for("drivers"))

        # If purpose is NOT "Security", require license and plate photos
        if purpose_of_visit.lower() not in ["security", "guardia"]:
            if not photo_data:
                error_message = "Driver license photo is required"
                print(f"❌ {error_message}\n")
                if is_ajax:
                    return jsonify({"success": False, "message": error_message}), 400
                flash(error_message, "error")
                return redirect(url_for("drivers"))
            
            if not plate_photo_data:
                error_message = "License Plate photo is required"
                print(f"❌ {error_message}\n")
                if is_ajax:
                    return jsonify({"success": False, "message": error_message}), 400
                flash(error_message, "error")
                return redirect(url_for("drivers"))

        # Check if card is already assigned to an active driver
        existing_driver = Driver.query.filter_by(card_id=card_id, check_out_time=None).first()
        if existing_driver:
            error_message = "Card ID already in use by another driver"
            print(f"❌ {error_message}\n")
            if is_ajax:
                return jsonify({"success": False, "message": error_message}), 400
            flash(error_message, 'error')
            return redirect(url_for('drivers'))

        # Save photos if provided
        photo_path = None
        plate_photo_path = None

        if photo_data:
            print("📌 Calling save_photo() for driver's license...")
            photo_path = save_photo(photo_data, truck_license, "driver_license")
            if photo_path:
                print(f"✅ Driver's License Photo saved at: {photo_path}\n")
            else:
                print("❌ Failed to save driver's license photo\n")

        if plate_photo_data:
            print("📌 Calling save_photo() for license plate...")
            plate_photo_path = save_photo(plate_photo_data, card_id, "plate_photos")
            if plate_photo_path:
                print(f"✅ License Plate Photo saved at: {plate_photo_path}\n")
            else:
                print("❌ Failed to save license plate photo\n")

        # ✅ Create new driver record
        new_driver = Driver(
            name=driver_name,
            provider_name=provider_name,
            truck_license=truck_license,
            card_id=card_id,
            purpose_of_visit=purpose_of_visit,
            point_of_contact=point_of_contact,
            photo_path=photo_path,
            plate_photo_path=plate_photo_path  # License Plate Photo
        )

        try:
            db.session.add(new_driver)
            db.session.commit()

            # ✅ Send security notification if purpose is "Security/Guardia"
            if purpose_of_visit.lower() in ["security", "guardia"]:
                send_security_notification(new_driver)

            print(f"✅ Driver added: {new_driver.name}, Card ID: {new_driver.card_id}, Check-out time: {new_driver.check_out_time}")

            # Query to verify the driver was added correctly
            added_driver = Driver.query.filter_by(card_id=new_driver.card_id).first()
            print(f"✅ Driver from DB: {added_driver.name}, Card ID: {added_driver.card_id}, Check-out time: {added_driver.check_out_time}")

            success_message = "Driver checked in successfully"

            if is_ajax:
                return jsonify({
                    "success": True,
                    "message": success_message,
                    "driver": {
                        "id": new_driver.id,
                        "name": new_driver.name,
                        "provider_name": new_driver.provider_name,
                        "truck_license": new_driver.truck_license,
                        "card_id": new_driver.card_id,
                        "purpose_of_visit": new_driver.purpose_of_visit,
                        "point_of_contact": new_driver.point_of_contact,
                        "photo_path": new_driver.photo_path,
                        "plate_photo_path": new_driver.plate_photo_path
                    }
                }), 200  # ✅ Returns JSON instead of redirecting

            flash(success_message, "success")
            return redirect(url_for("drivers"))  # ⛔️ Avoids redirect for AJAX

        except Exception as e:
            db.session.rollback()
            print(f"❌ Database error: {e}\n")

            error_message = "Database error occurred"
            if is_ajax:
                return jsonify({"success": False, "message": error_message}), 500

            flash(error_message, "error")
            return redirect(url_for("drivers"))

    # ✅ GET request - display all active drivers
    active_drivers = Driver.query.filter_by(check_out_time=None).all()


    for driver in active_drivers:
        if driver.check_in_time:
            if driver.check_in_time.tzinfo is None:
                 # Create aware datetime by assuming it's in local time already
                aware_time = LOCAL_TZ.localize(driver.check_in_time, is_dst=None)
            else:
                aware_time = driver.check_in_time.astimezone(LOCAL_TZ)
            driver.formatted_check_in = aware_time.strftime('%Y-%m-%d %I:%M %p')
        else:
            driver.formatted_check_in = "No check-in time"

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"success": True, "drivers": [d.to_dict() for d in active_drivers]})

    return render_template("drivers.html", drivers=active_drivers)


@app.route("/checkout/<card_id>", methods=["POST"])
def checkout(card_id):
    driver = Driver.query.filter_by(card_id=card_id, check_out_time=None).first()
    
    if not driver:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "message": "Driver not found or already checked out"}), 404
        flash("Driver not found or already checked out", "error")
        return redirect(url_for("drivers"))
    
    try:
        # Create a timezone-aware datetime object using LOCAL_TZ
        driver.check_out_time = datetime.now(LOCAL_TZ).replace(microsecond=0)
        db.session.commit()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": True, "message": "Driver checked out successfully"}), 200
            
        flash("Driver checked out successfully", "success")
        return redirect(url_for("drivers"))
        
    except Exception as e:
        db.session.rollback()
        print(f"Error checking out driver: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "message": "Database error occurred"}), 500
            
        flash("An error occurred while checking out the driver", "error")
        return redirect(url_for("drivers"))
    

@app.route("/check-db")
def check_db():
    all_drivers = Driver.query.all()
    result = []
    for driver in all_drivers:
        result.append({
            "id": driver.id,
            "name": driver.name,
            "card_id": driver.card_id,
            "check_in_time": str(driver.check_in_time),
            "check_out_time": str(driver.check_out_time)
        })
    return jsonify(result)

@app.route('/diagnose')
def diagnose():
    try:
        # Get the actual database file path from your configuration
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')

        # Check all drivers
        all_drivers = Driver.query.all()

        # Check active drivers
        active_drivers = Driver.query.filter_by(check_out_time=None).all()

        # Build diagnostic information
        result = {
            "database_uri": app.config['SQLALCHEMY_DATABASE_URI'],
            "database_file_path": db_path,
            "database_file_exists": os.path.exists(db_path),
            "total_drivers": len(all_drivers),
            "active_drivers": len(active_drivers),
            "all_drivers": [
                {
                    "id": d.id,
                    "name": d.name,
                    "card_id": d.card_id,
                    "check_in_time": str(d.check_in_time),
                    "check_out_time": str(d.check_out_time)
                } for d in all_drivers
            ]
        }

        return jsonify(result)  # ✅ Properly indented inside try block

    except Exception as e:
        return jsonify({"error": str(e)})  # ✅ Properly indented at the same level as try
    

#email functionality
def send_security_notification(driver):
    try:
        #format timstamp for email
        check_in_time = driver.check_in_time.strftime('%Y-%m-%d %H:%M:%S')

        #Email Recipients
        recipients = [
            #'jorge.prado@royalexpressinc.com',
            'geraldina@royalexpressinc.com',
            'brayan.colmenares@royalexpressinc.com',
            'marcol@royalexpressinc.com',
            'mrenteria@royalexpressinc.com'
        ]

        #Email Subject
        subject = f"Interchange Check-In Alert: {driver.name}"

        #email body
        email_body = f'''
        <html>
        <body>
            <h2>InterExchange Check-In Notification</h2>
            <p>A driver has checked in with an Interchange purpose:</p>
            <table border="1" cellpadding="5" style="border-collapse: collapse;">
                <tr><th>Name</th><td>{driver.name}</td></tr>
                <tr><th>Provider</th><td>{driver.provider_name}</td></tr>
                <tr><th>License</th><td>{driver.truck_license}</td></tr>
                <tr><th>Card ID</th><td>{driver.card_id}</td></tr>
                <tr><th>Purpose of Visit</th><td>{driver.purpose_of_visit}</td></tr>
                <tr><th>Point of Contact</th><td>{driver.point_of_contact}</td></tr>
                <tr><th>Check-in Time</th><td>{driver.check_in_time}</td></tr>
            </table>
        </body>
        </html>
        '''

        #prepare attatchments
        attachments = []

        #attatch photo to email
        if driver.photo_path:
            photo_path = os.path.join(app.static_folder, driver.photo_path)
            if os.path.exists(photo_path):
                with open(photo_path, "rb") as f:
                    photo_data = f.read()
                    photo_base64 = base64.b64decode(photo_data).decode('utf-8')

                #get the filename from the path
                filename = os.path.basename(driver.photo_path)

                #add attachment
                attachments.append({
                    "name": filename,
                    "data": photo_base64,
                    "content_type": "image/jpeg"
                })


        #api response payload
        payload = {
            "api_key": SMTP2GO_API_KEY,
            "to": recipients,
            "sender": SENDER_EMAIL,
            "subject": subject,
            "html_body": email_body,
        }

        #Send api request
        response = requests.post(SMTP2GO_API_URL, json=payload)

        #log the response
        print(f"Email notification sent. Response: {response.status_code}, {response.text}")

        return response.status_code == 200
    
    except Exception as e:
        print(f"Failure to send email notification {e}")
        return False
    
                







#Photos
@app.route("/photo/<path:filename>")
def get_photo(filename):
    return send_from_directory(os.path.join(app.static_folder, 'uploads'), filename)



@app.route("/fix-photo-paths")
def fix_photo_paths():
    drivers = Driver.query.all()
    for driver in drivers:
        if driver.photo_path:
            # Fix backslashes to forward slashes
            fixed_path = driver.photo_path.replace('\\', '/')
            # Remove any %5C encoding
            fixed_path = fixed_path.replace('%5C', '/')
            # Make sure there's no double slashes
            while '//' in fixed_path:
                fixed_path = fixed_path.replace('//', '/')
            # Update only if needed
            if fixed_path != driver.photo_path:
                driver.photo_path = fixed_path
    
    db.session.commit()
    return "Photo paths fixed"




#secret key for sessions
app.secret_key = "your_secret_key"

#session to expire after 1 hour
app.permanent_session_lifetime = timedelta(hours=1)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if username == 'admin' and password == 'royal25':
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('login.html', error='Invalid Credentials')
        
    return render_template('login.html')
'''
def authenticate():
    send authenthication challenge
    return Response(
        'Could not verify your access level for this page.\n'
        'Please login with proper credentials', 401,
        {'WWW-Authenticate': 'Basic realm="Admin Dashboard"'} )'''
    
def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# dictionary to map Spanish values to English
purpose_translations = {
    "entrega de productos": "Product Delivery",
    "reunión": "Meeting",
    "inspeccion": "Inspection",
    "reparacion de cajas": "Trailer Repair",
    "Guardia": "Security",
    "otros": "Other"
}


@app.route('/admin-panel-royal', methods=["GET"])
@requires_auth
def admin_dashboard():
    # Get all drivers including checked out ones
    all_drivers = Driver.query.order_by(Driver.check_in_time.desc()).all()
    
    for driver in all_drivers:
        # Format check-in time
        if driver.check_in_time:
            # Use astimezone instead of localize to handle DST properly
            if driver.check_in_time.tzinfo is None:
                # Create aware datetime by assuming it's in local time already
                aware_time = LOCAL_TZ.localize(driver.check_in_time, is_dst=None)
            else:
                aware_time = driver.check_in_time.astimezone(LOCAL_TZ)
            
            driver.formatted_check_in = aware_time.strftime('%Y-%m-%d %I:%M %p')
        else:
            driver.formatted_check_in = "No check-in time"
        
        # Format check-out time - use the same approach for consistency
        if driver.check_out_time:
            if driver.check_out_time.tzinfo is None:
                # Create aware datetime by assuming it's in local time already
                aware_time = LOCAL_TZ.localize(driver.check_out_time, is_dst=None)
            else:
                aware_time = driver.check_out_time.astimezone(LOCAL_TZ)
            
            driver.formatted_checkout = aware_time.strftime('%Y-%m-%d %I:%M %p')
        else:
            driver.formatted_checkout = "Still in warehouse"
    
    return render_template("admin.html", drivers=all_drivers, purpose_translations=purpose_translations)

#route to handle admin exit event
@app.route('/admin-exit', methods=['POST', 'GET'])
def admin_exit():
    #clear the admin session when they leave the admin panel
    session.pop('logged_in', None)
    return '', 204 #return empty respinse with "No content" status

@app.route('/check-model')
def check_model():
    # Get information about the Driver table
    table_info = []
    with app.app_context():
        columns = db.engine.execute("PRAGMA table_info(driver)").fetchall()
        for column in columns:
            table_info.append({
                'name': column[1],
                'type': column[2],
                'nullable': column[3] == 0  # 0 means NULL is allowed
            })
    return jsonify(table_info)



if __name__ == "__main__":
     # Get the port from an environment variable or use 5000 as default
    port = int(os.environ.get('PORT', 5001))
    
    # Initialize your database tables
    with app.app_context():
        db.create_all()
    
    # Set debug mode based on environment
    in_development = os.environ.get('FLASK_ENV') == 'development'
    
    # Run the app with the dynamic port, debug off for production
    app.run(debug=in_development, host="0.0.0.0", port=port)