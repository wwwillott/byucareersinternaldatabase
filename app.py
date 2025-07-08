from flask import Flask, request, render_template, redirect, flash, session, Response, jsonify
import pymssql  # uses easier connection than pyodbc
from datetime import datetime, time
import csv
import io

app = Flask(__name__)

app.secret_key = 'supersecretkey'  # Change this to a random secret key in production

def get_season_background():
    month = datetime.now().month
    if month in [12, 1, 2]:
        return 'winter.png'
    elif month in [3, 4, 5]:
        return 'spring.jpg'
    elif month in [6, 7, 8]:
        return 'summer.jpg'
    else:
        return 'fall.jpg'

def safe_parse_time(t):
    if isinstance(t, time):  # already a time object
        return t.strftime('%H:%M:%S')
    t = str(t).strip()
    try:
        return datetime.strptime(t, '%H:%M:%S').time().strftime('%H:%M:%S')
    except ValueError:
        try:
            return datetime.strptime(t, '%H:%M').time().strftime('%H:%M:%S')
        except ValueError:
            return None

def get_connection():
    return pymssql.connect(
        server='byucareerservices.database.windows.net',
        user='willott@byucareerservices.database.windows.net',
        password='Willisthebest17',
        database='Career_Services_Database'
    )

def get_primary_key_column(table_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE OBJECTPROPERTY(
          OBJECT_ID(CONSTRAINT_SCHEMA + '.' + CONSTRAINT_NAME),
          'IsPrimaryKey'
        ) = 1
        AND TABLE_NAME = '{table_name}'
    """)
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def normalize_time(value):
    """Convert HH:MM or HH:MM:SS to HH:MM:SS; returns None if invalid or empty"""
    value = value.strip()
    if not value:
        return None
    try:
        # Try HH:MM format
        return datetime.strptime(value, "%H:%M").time().strftime("%H:%M:%S")
    except ValueError:
        try:
            # Try HH:MM:SS format
            return datetime.strptime(value, "%H:%M:%S").time().strftime("%H:%M:%S")
        except ValueError:
            return None  # Or raise an error/flash message
        
def clean_value(val, col=None):
    if val is None:
        return None
    val = str(val).strip()
    if val == '' or val.lower() == 'none':
        return None
    if col in ['StartTime', 'EndTime']:
        normalized = normalize_time(val)
        if normalized is None:
            # You could also flash here or raise error if you want strict validation
            return None
        return normalized
    return val

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/editor/<table_name>')
def editor(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table_name,))
    columns = [row[0] for row in cursor.fetchall()]

    conn.close()
    return render_template('editor.html', table_name=table_name, columns=columns)

@app.route('/add_row/<table_name>', methods=['POST'])
def add_row(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()

    columns = []
    values = []

    for key, value in request.form.items():
        if key.startswith("column_"):
            column_name = key.replace("column_", "")
            cleaned_val = clean_value(value, column_name)
            if cleaned_val is None and value.strip() != '':
                flash(f"Invalid value for {column_name}.", 'danger')
                return redirect(request.referrer)
            columns.append(column_name)
            values.append(cleaned_val)

    if columns:
        placeholders = ', '.join(['%s'] * len(values))
        column_names = ', '.join(columns)
        query = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
        cursor.execute(query, tuple(values))
        conn.commit()

    conn.close()
    return redirect(f'/view/{table_name}')

@app.route('/editor_wizard/<table_name>')
def editor_wizard(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table_name,))
    columns = [row[0] for row in cursor.fetchall()]
    conn.close()

    column_descriptions = {
        # 'InfoSessions' table
        'EventID': 'To get the ID, go to the Info Session event on Handshake and copy the number at the end of the URL.',
        'EmployerName': 'The name of the employer as it appears on Handshake.',
        'Weekday': 'The day of the week for the event.',
        'EventDate': 'The date of the event in YYYY-MM-DD format. Please type it exactly as shown or the system will not recognize it. Ex. 2027-07-17',
        'EventTime': 'The time of the event in HH:MM 24h format. Please type it exactly as shown or the system will not recognize it. Ex. 14:00',
        # 'Employers' table
        'EmployerID': "To get the ID, go to the Employer's profile on Handshake and copy the number at end of the URL.",
        # 'Interviews' table
        'InterviewID': 'To get the ID, go to the Interview event on Handshake and copy the number at the end of the URL.'
    }

    dropdown_options = {
        'RoomType': ['Pre-Select', 'Room Only'],
        'Weekday': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    }

    return render_template('editor_wizard.html',
                           table_name=table_name,
                           columns=columns,
                           column_descriptions=column_descriptions,
                           dropdown_options=dropdown_options)

@app.route('/advanced_editor/<table_name>')
def advanced_editor(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404
    return render_template('advanced_editor.html', table_name=table_name)

@app.route('/download_template/<table_name>')
def download_template(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    # Connect and get columns for this table
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table_name,))
    columns = [row[0] for row in cursor.fetchall()]
    conn.close()

    # Create CSV in memory with just headers (no rows)
    def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        yield output.getvalue()

    headers = {
        "Content-Disposition": f"attachment; filename={table_name}_template.csv",
        "Content-Type": "text/csv",
    }
    return Response(generate(), headers=headers)

@app.route('/upload_csv/<table_name>', methods=['GET', 'POST'])
def upload_csv(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    if request.method == 'GET':
        return render_template('upload_csv.html', table_name=table_name)

    # POST handler (final confirm insert)
    headers = session.get('csv_headers')
    data = session.get('csv_data')

    if not headers or not data:
        return "No CSV data found in session.", 400
    
    conn = get_connection()
    cursor = conn.cursor()

    placeholders = ', '.join(['%s'] * len(headers))
    columns = ', '.join(f"[{col}]" for col in headers)
    insert_query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

    for row in data:
        cleaned_row = [clean_value(val, col) for val, col in zip(row, headers)]
        cursor.execute(insert_query, tuple(cleaned_row))

    conn.commit()
    conn.close()

    # Clear session
    session.pop('csv_headers', None)
    session.pop('csv_data', None)

    return redirect(f'/view/{table_name}')


@app.route('/preview_csv/<table_name>', methods=['POST'])
def preview_csv(table_name):
    from flask import session, flash, redirect, url_for
    import csv
    import io

    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    file = request.files.get('csv_file')
    if not file or not file.filename.endswith('.csv'):
        flash('Please upload a valid CSV file.', 'danger')
        return redirect(url_for('upload_csv', table_name=table_name))

    contents = file.read().decode('utf-8')
    reader = csv.reader(io.StringIO(contents))
    rows = list(reader)

    if not rows:
        flash('CSV file is empty.', 'danger')
        return redirect(url_for('upload_csv', table_name=table_name))

    headers = rows[0]
    data = rows[1:]

    # Get DB columns for validation
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table_name,))
    expected_columns = [row[0] for row in cursor.fetchall()]
    conn.close()

    # Validate headers
    if set(headers) - set(expected_columns):
        flash("CSV contains unknown columns.", "danger")
        return redirect(url_for('upload_csv', table_name=table_name))

    # Save to session for confirmation step
    session['csv_headers'] = headers
    session['csv_data'] = data

    return render_template('csv_preview.html', table_name=table_name, headers=headers, rows=data)

@app.route('/view/<table_name>', methods=['GET', 'POST'])
def view_table(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()

    # Get all column names (always needed for checkboxes)
    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table_name,))
    all_columns = [row[0] for row in cursor.fetchall()]

    # If POST, filter selected columns
    selected_columns = request.form.getlist('columns') if request.method == 'POST' else all_columns

    if not selected_columns:
        selected_columns = all_columns  # fallback if nothing selected

    column_str = ', '.join(f'[{col}]' for col in selected_columns)  # [] for SQL Server compatibility
    cursor.execute(f"SELECT {column_str} FROM {table_name}")
    rows = cursor.fetchall()

    conn.close()
    return render_template(
        'viewer.html',
        table_name=table_name,
        columns=selected_columns,
        rows=rows,
        all_columns=all_columns,
        selected_columns=selected_columns
    )

@app.route('/delete/<int:EmployerID>', methods=['POST'])
def delete_row(EmployerID):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM Employers WHERE EmployerID = %s", (EmployerID,))
    conn.commit()
    conn.close()

    return redirect('/view/Employers')

@app.route('/delete_mode/<table_name>')
def delete_mode(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = '{table_name}' 
        ORDER BY ORDINAL_POSITION
    """)
    columns = [row[0] for row in cursor.fetchall()]
    pk_column = get_primary_key_column(table_name) or columns[0]  # Fallback to first column if no PK found

    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()

    conn.close()
    return render_template('delete_mode.html', table_name=table_name, columns=columns, rows=rows, pk_column=pk_column)


@app.route('/confirm_delete/<table_name>', methods=['POST'])
def confirm_delete(table_name):
    row_ids = request.form.getlist('row_ids')
    pk_column = request.form.get('pk_column')
    return render_template('confirm_delete.html', table_name=table_name, row_ids=row_ids, pk_column=pk_column)


@app.route('/final_delete/<table_name>', methods=['POST'])
def final_delete(table_name):
    row_ids = request.form.getlist('row_ids')
    pk_column = request.form.get('pk_column')
    if not row_ids or not pk_column:
        return redirect(f'/view/{table_name}')

    conn = get_connection()
    cursor = conn.cursor()

    print("Deleting from:", table_name)
    print("PK column:", pk_column)
    print("Row IDs:", row_ids)

    # Assumes first column is primary key
    placeholders = ','.join(['%s'] * len(row_ids))
    query = f"DELETE FROM {table_name} WHERE {pk_column} IN ({placeholders})"
    cursor.execute(query, tuple(row_ids))
    conn.commit()
    conn.close()

    return redirect(f'/view/{table_name}')

@app.route('/edit_mode/<table_name>', methods=['GET', 'POST'])
def edit_mode(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = '{table_name}' 
        ORDER BY ORDINAL_POSITION
    """)
    columns = [row[0] for row in cursor.fetchall()]
    pk_column = get_primary_key_column(table_name) or columns[0]

    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    conn.close()

    return render_template('edit_mode.html', table_name=table_name, columns=columns, rows=rows, pk_column=pk_column)

@app.route('/edit_row_form/<table_name>', methods=['POST'])
def edit_row_form(table_name):
    row_id = request.form.get('row_id')
    pk_column = request.form.get('pk_column')

    if not row_id or not pk_column:
        return redirect(f'/edit_mode/{table_name}')

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = '{table_name}' 
        ORDER BY ORDINAL_POSITION
    """)
    columns = [row[0] for row in cursor.fetchall()]

    cursor.execute(f"SELECT * FROM {table_name} WHERE [{pk_column}] = %s", (row_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "Row not found", 404

    return render_template("edit_row_form.html", table_name=table_name, columns=columns, row=row, pk_column=pk_column)

@app.route('/submit_edit/<table_name>', methods=['POST'])
def submit_edit(table_name):
    pk_column = request.form.get('pk_column')
    row_id = request.form.get('row_id')

    if not pk_column or not row_id:
        return redirect(f'/view/{table_name}')

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = '{table_name}' 
        ORDER BY ORDINAL_POSITION
    """)
    columns = [row[0] for row in cursor.fetchall()]

    # Build update query
    update_clauses = []
    values = []

    for col in columns:
        if col == pk_column:
            continue
        update_clauses.append(f"[{col}] = %s")
        raw_value = request.form.get(col, '')
        cleaned_val = clean_value(raw_value, col)
        if cleaned_val is None and raw_value.strip() != '':
            flash(f"Invalid value for {col}.", 'danger')
            return redirect(request.referrer)
        values.append(cleaned_val)

    values.append(row_id)

    query = f"UPDATE {table_name} SET {', '.join(update_clauses)} WHERE [{pk_column}] = %s"
    cursor.execute(query, values)
    conn.commit()
    conn.close()

    return redirect(f'/view/{table_name}')

@app.route('/calendar_events')
def calendar_events():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT EventID, EmployerName, EventDate, StartTime, EndTime , Building, Room
        FROM InfoSessions
        WHERE EventDate IS NOT NULL AND StartTime IS NOT NULL
    """)

    events = []
    for event_id, name, date, start, end, building, room in cursor.fetchall():
        if not date or not start:
            continue

        date_str = date.isoformat() if isinstance(date, datetime) else str(date)
        start_str = safe_parse_time(start)
        end_str = safe_parse_time(end) if end else None

        if not start_str:
            continue  # skip if we can't parse time

        location = f"{building or ''} {room or ''}".strip()
        handshake_url = f"https://byu.joinhandshake.com/stu/events/{event_id}"

        event = {
            'title': name,
            'start': f"{date_str}T{start_str}",
            'location': location,
            'link': handshake_url
        }
        if end_str:
            event['end'] = f"{date_str}T{end_str}"

        events.append(event)

    conn.close()
    return jsonify(events)

@app.route('/calendar')
def calendar_view():
    return render_template('calendar.html')

@app.route('/two_week_preview_events')
def two_week_preview_events():
    from datetime import datetime, timedelta
    major_group = request.args.get('major_group')

    conn = get_connection()
    cursor = conn.cursor()

    today = datetime.today().date()
    end_date = today + timedelta(days=14)

    query = """
        SELECT EventID, EmployerName, EventDate, StartTime, EndTime, Building, Room, MajorGroup
        FROM InfoSessions
        WHERE EventDate BETWEEN %s AND %s
    """
    params = [today, end_date]

    if major_group:
        query += " AND MajorGroup = %s"
        params.append(major_group)

    cursor.execute(query, tuple(params))

    events = []
    for event_id, name, date, start, end, building, room, group in cursor.fetchall():
        start_time_str = safe_parse_time(start) if start else "00:00:00"
        end_time_str = safe_parse_time(end) if end else None

        start_str = f"{date}T{start_time_str}"
        end_str = f"{date}T{end_time_str}" if end_time_str else None

        location = f"{building or ''} {room or ''}".strip()

        event = {
            'title': f"{name} ({group})",  # Include major group visibly
            'start': start_str,
            'extendedProps': {
                'location': location,
                'link': f"https://byu.joinhandshake.com/stu/events/{event_id}",
                'major_group': group
            }
        }
        if end_str:
            event['end'] = end_str

        events.append(event)

    conn.close()
    return jsonify(events)

@app.route('/two_week_preview')
def two_week_preview():
    return render_template('two_week_preview.html')

@app.route('/konami')
def konami():
    return render_template('konami.html')

@app.context_processor
def inject_background_image():
    return dict(background_image=get_season_background())

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(404)
def internal_server_error(e):
    return render_template('404.html'), 404

@app.errorhandler(403)
def internal_server_error(e):
    return render_template('403.html'), 403

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)