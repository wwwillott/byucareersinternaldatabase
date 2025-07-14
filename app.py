from flask import Flask, request, render_template, redirect, flash, session, Response, jsonify, url_for, send_file
import pymssql  # uses easier connection than pyodbc
from datetime import datetime, time, date
import csv
import io
import json
import os
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

app.secret_key = 'supersecretkey'  # Change this to a random secret key in production

#link bit.ly/byucareersdatabase this can be changed using SSO on bitly

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

def archive_past_infosessions():
    conn = get_connection()
    cursor = conn.cursor()

    # Select past sessions
    cursor.execute("""
        SELECT EventID, EmployerName, EventDate, StartTime, EndTime, Building, Room, Food, MajorGroup
        FROM InfoSessions
        WHERE EventDate < %s
    """, (date.today(),))

    rows = cursor.fetchall()

    # Insert into archive
    for row in rows:
        cursor.execute("""
            INSERT INTO InfoSessionsArchive (
                EventID, EmployerName, EventDate, StartTime, EndTime,
                Building, Room, Food, MajorGroup,
                Attendees, Debrief
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
        """, row)

    # Delete from original
    cursor.execute("""
        DELETE FROM InfoSessions WHERE EventDate < %s
    """, (date.today(),))

    conn.commit()
    conn.close()

# Helpful functions for database connections and data cleaning
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
    """Convert HH:MM or HH:MM:SS string to a Python time object; returns None if invalid or empty"""
    value = value.strip()
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.time()  # Return Python time object
        except ValueError:
            continue
    return None  # invalid format

def clean_value(val, col=None):
    if val is None:
        return None
    val = str(val).strip()
    if val == '' or val.lower() == 'none':
        return None
    
    if col in ['StartTime', 'EndTime']:
        normalized_time = normalize_time(val)  # This returns a datetime.time object or None
        if normalized_time is None:
            return None
        return normalized_time.strftime("%H:%M:%S")

    # Convert numeric columns appropriately (adjust column names if needed)
    if col in ['Attendees']:
        try:
            return int(val)
        except ValueError:
            return None
    
    # For dates, check if it's already a date object before converting to string
    if col == 'EventDate':
        if isinstance(val, date):
            return val  # Already a date object, return as-is
        if isinstance(val, datetime):
            return val.date()  # Convert datetime to date

    # For times, check if it's already a time object  
    if col in ['StartTime', 'EndTime']:
        if isinstance(val, time):
            return val.strftime("%H:%M:%S")
    
    return val


# Homepage
@app.route('/')
def index():
    return render_template('index.html')

# Helper function to get input from form or query parameters
def get_input(name, default=''):
    return request.form.get(name, request.args.get(name, default)).strip()

# Search functionality
@app.route('/search_all', methods=['GET', 'POST'])
def search_all():
    query = get_input('query')
    selected_table = get_input('table_filter')
    start_date = get_input('start_date')
    end_date = get_input('end_date')
    search_column = get_input('search_column')
    search_text = get_input('search_text')

    # Convert dates if valid
    try:
        start_date_parsed = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
    except ValueError:
        start_date_parsed = None

    try:
        end_date_parsed = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
    except ValueError:
        end_date_parsed = None

    # If no filter, search just InfoSessions and Interviews separately
    if not selected_table:
        tables = ['InfoSessions', 'Interviews']
    else:
        tables = [selected_table]

    # Prepare results containers
    info_sessions_results = []
    interviews_results = []
    other_results = []  # For other tables if filtered

    conn = get_connection()
    cursor = conn.cursor()

    for tbl in tables:
        cursor.execute(f"SELECT * FROM {tbl}")
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

        for row in rows:
            row_dict = dict(zip(columns, row))

            # Match text search
            if query and not any(query.lower() in str(v).lower() for v in row_dict.values()):
                continue

            # Match specific column search
            if search_column and search_text:
                if search_column not in row_dict:
                    continue
                if search_text.lower() not in str(row_dict[search_column]).lower():
                    continue

            # Match date filter - try known date-related columns
            for date_col in ['EventDate', 'StartDate', 'EndDate']:
                if date_col in row_dict:
                    date_val = row_dict[date_col]
                    if isinstance(date_val, datetime):
                        date_val = date_val.date()
                    elif not isinstance(date_val, date):
                        continue

                    if start_date_parsed and date_val < start_date_parsed:
                        continue
                    if end_date_parsed and date_val > end_date_parsed:
                        continue
                    break  # matched a valid date column, no need to keep checking
            else:
                # If none of the date columns exist or match, skip
                if start_date_parsed or end_date_parsed:
                    continue

            # Append results based on table
            if tbl == 'InfoSessions':
                info_sessions_results.append(row_dict)
            elif tbl == 'Interviews':
                interviews_results.append(row_dict)
            else:
                other_results.append(row_dict)

    conn.close()

    # If filtered to one table other than InfoSessions/Interviews, show single results table
    if selected_table and selected_table not in ['InfoSessions', 'Interviews']:
        return render_template(
            'search.html',
            results=other_results,
            query=query,
            selected_table=selected_table,
            start_date=start_date,
            end_date=end_date,
            search_column=search_column,
            search_text=search_text
        )

    columns_for_autocomplete = [
        'EventID','EmployerName','Weekday','EventDate','StartTime','EndTime',
        'Building','Room','StudentHost','ContactName','ContactEmail','ContactPhone',
        'Food','Majors','PreferredLocation','Notes','MajorGroup','Attendees','Debrief',
        'InterviewID','RoomCount','RoomType','InterviewerName','InterviewerEmail','PrintedLogo',
        # add any other relevant column names here
    ]

    safe_columns_json = json.dumps(columns_for_autocomplete).replace("'", "\\'")

    # Else show separate results for InfoSessions and Interviews if no filter or filter on those two
    return render_template(
        'search.html',
        info_sessions_results=info_sessions_results,
        interviews_results=interviews_results,
        query=query,
        selected_table=selected_table,
        start_date=start_date,
        end_date=end_date,
        search_column=search_column,
        search_text=search_text,
        all_columns=safe_columns_json
    )


# Add row routes
@app.route('/editor/<table_name>')
def editor(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers', 'InfoSessionsArchive']
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
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers', 'InfoSessionsArchive']
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
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers', 'InfoSessionsArchive']
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
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers','InfoSessionsArchive']
    if table_name not in allowed_tables:
        return "Table not found", 404
    return render_template('advanced_editor.html', table_name=table_name)

# Still add row, but for CSV upload/download functionality
@app.route('/download_template/<table_name>')
def download_template(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers','InfoSessionsArchive']
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
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers','InfoSessionsArchive']
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

    allowed_tables = ['InfoSessions', 'Interviews', 'Employers','InfoSessionsArchive']
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



# Table viewer route
@app.route('/view/<table_name>', methods=['GET', 'POST'])
def view_table(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers', 'InfoSessionsArchive']
    if table_name not in allowed_tables:
        return "Hey, that's no table! You must've done something wrong...", 404

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

@app.route('/toggle_archive/<base_table>')
def toggle_archive(base_table):
    session_key = f"{base_table}_archive_mode"
    session[session_key] = not session.get(session_key, False)

    # Pick the appropriate table name
    table = f"{base_table}Archive" if session[session_key] else base_table
    return redirect(url_for('view_table', table_name=table))

# Delete row functionality
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
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers','InfoSessionsArchive']
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



# Edit row functionality
@app.route('/edit_mode/<table_name>', methods=['GET', 'POST'])
def edit_mode(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers', 'InfoSessionsArchive']
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

@app.route('/edit_row_form/<table_name>', methods=['GET','POST'])
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
    print("DEBUG: submit_edit route hit!")
    
    pk_column = request.form.get('pk_column')
    row_id = request.form.get('row_id')

    if not pk_column or not row_id:
        print("DEBUG: Missing pk_column or row_id, redirecting back.")
        return redirect(f'/edit_mode/{table_name}')

    # Try converting row_id to int if possible (adjust if your PK is not int)
    try:
        row_id_int = int(row_id)
        print(f"DEBUG: Converted row_id to int: {row_id_int}")
    except Exception as e:
        print(f"DEBUG ERROR: Cannot convert row_id to int: {e}")
        # If your PK is string, you can just keep row_id as is
        row_id_int = row_id  # fallback

    conn = get_connection()
    cursor = conn.cursor()

    # Fetch columns BEFORE accessing form data
    cursor.execute(f"""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = '{table_name}' 
        ORDER BY ORDINAL_POSITION
    """)
    columns = [row[0] for row in cursor.fetchall()]
    print(f"DEBUG: Columns in table: {columns}")

    print("---- FORM DATA ----")
    for col in columns:
        val = request.form.get(col)
        print(f"{col}: {val}")

    # Build update clauses and values list for SQL
    update_clauses = []
    values = []

    for col in columns:
        if col == pk_column:
            continue  # skip PK in update set
        raw_value = request.form.get(col, '')
        cleaned_val = clean_value(raw_value, col)  # call your existing function

        # If clean_value returned a datetime.time object, convert to string for SQL
        if hasattr(cleaned_val, 'strftime'):
            cleaned_val = cleaned_val.strftime("%H:%M:%S")

        update_clauses.append(f"[{col}] = %s")
        values.append(cleaned_val)

    # Append the PK value for the WHERE clause
    values.append(row_id_int)

    query = f"UPDATE {table_name} SET {', '.join(update_clauses)} WHERE [{pk_column}] = %s"

    print(f"DEBUG: Executing query:\n{query}\nWith values:\n{values}")

    try:
        cursor.execute(query, values)
        print(f"DEBUG: Rows affected: {cursor.rowcount}")
        conn.commit()
    except Exception as e:
        print(f"DEBUG ERROR: Exception executing update: {e}")
        flash(f"Database error: {e}", 'danger')
        conn.rollback()
    finally:
        conn.close()

    return redirect(f'/edit_mode/{table_name}')


@app.route('/test_update')
def test_update():
    conn = get_connection()
    cursor = conn.cursor()
    test_pk = 123  # your sample PK
    try:
        cursor.execute("UPDATE InfoSessionsArchive SET Notes = 'Test update' WHERE [EventID] = %s", (test_pk,))
        conn.commit()
        affected = cursor.rowcount
    except Exception as e:
        conn.rollback()
        return f"Error during test update: {e}"
    finally:
        conn.close()
    return f"Test update complete, rows affected: {affected}"



# Calendar display routes
@app.route('/calendar_events')
def calendar_events():
    conn = get_connection()
    cursor = conn.cursor()

    def fetch_events_from(table_name):
        cursor.execute(f"""
            SELECT EventID, EmployerName, EventDate, StartTime, EndTime, Building, Room
            FROM {table_name}
            WHERE EventDate IS NOT NULL
        """)
        results = []
        for event_id, name, event_date, start, end, building, room in cursor.fetchall():
            if not event_date:
                continue

            # Convert date to ISO string (YYYY-MM-DD)
            if isinstance(event_date, datetime):
                date_only = event_date.date()
            else:
                date_only = event_date

            # Compose start datetime string combining date + time
            if start is None:
                start_str = None
            else:
                # start may be a time object or string; convert to string "HH:MM:SS"
                if isinstance(start, (datetime, )):
                    start_time_str = start.time().isoformat()
                elif isinstance(start, str):
                    start_time_str = start
                else:
                    start_time_str = str(start)

                start_str = f"{date_only}T{start_time_str}"

            # Same for end time if exists
            if end is None:
                end_str = None
            else:
                if isinstance(end, (datetime, )):
                    end_time_str = end.time().isoformat()
                elif isinstance(end, str):
                    end_time_str = end
                else:
                    end_time_str = str(end)
                end_str = f"{date_only}T{end_time_str}"

            location = f"{building or ''} {room or ''}".strip()
            handshake_url = f"https://byu.joinhandshake.com/stu/events/{event_id}"


            event = {
                'title': name,
                'start': start_str,
                'location': location,
                'link': handshake_url
            }
            if end_str:
                event['end'] = end_str

            results.append(event)
        return results


    # Combine events from both tables
    events = fetch_events_from("InfoSessions") + fetch_events_from("InfoSessionsArchive")

    conn.close()
    return jsonify(events)

@app.route('/calendar')
def calendar_view():
    return render_template('calendar.html')

@app.route('/two_week_preview_events')
def two_week_preview_events():
    from datetime import datetime, timedelta
    major_group = request.args.get('major_group')
    start = request.args.get('start')
    end = request.args.get('end')

    if not start or not end:
        return jsonify([])
    
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT EventID, EmployerName, EventDate, StartTime, EndTime, Building, Room, MajorGroup
        FROM InfoSessions
        WHERE EventDate BETWEEN %s AND %s
    """
    params = [start, end]

    if major_group:
        query += " AND MajorGroup = %s"
        params.append(major_group)

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    if not rows:
        return jsonify([])
    
    #debugs
    print("Query params:", start, end)
    print("Row count:", cursor.rowcount)
    print("First 3 rows:", rows[:3])

    events = []
    for event_id, name, date, start, end, building, room, group in rows:
        print(f"🔹 Raw row: {event_id}, {name}, {date}, {start}, {end}, {building}, {room}, {group}")
    
        start_time_str = safe_parse_time(start) if start else "00:00:00"
        if not start_time_str:
            print(f"❌ Could not parse start time: {start}")
            continue

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

    # dEBUG
    import pprint
    pprint.pprint(events)

    conn.close()
    return jsonify(events=events)

@app.route('/two_week_preview')
def two_week_preview():
    return render_template('two_week_preview.html')

# Map Builder
room_coords = {
    "EB": {
        "101": (100, 150),  # Room 101 on EB_1.png
        #200's
        "201": (120, 180),  # Room 201 on EB_2.png
        "224": (600, 675),  # Room 224 on EB_2.png
        "246-6": (600, 675),  # also Room 224 on EB_2.png
        "222": (700, 675),  # Room 222 on EB_2.png
        "246-5": (700, 675),  # also Room 224 on EB_2.png
        "246G": (1162, 308),  # Room 246G on EB_2.png
        "246-4": (1162, 308),  # also Room 246G on EB_2.png
        "246L": (1331,308),  # Room 246L on EB_2.png
        "246-3": (1331,308),  # also Room 246L on EB_2.png
        "246M": (1415, 308),  # Room 246M on EB_2.png
        "246-2": (1415, 308),  # also Room 246M on EB_2.png
        "246N": (1505, 308),  # Room 246N on EB_2.png
        "246-1": (1505, 308),  # also Room 246N on EB_2.png
    },
}

def annotate_map(map_path, room_employers, output_path, building):
    img = Image.open(map_path).convert('RGB')
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    for room, employer in room_employers:
        coord = room_coords.get(building, {}).get(room)
        if not coord:
            continue

        x, y = coord
        r = 12  # highlight radius
        draw.ellipse((x - r, y - r, x + r, y + r), fill='red')
        draw.text((x + r + 2, y - r), employer, fill='black', font=font)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, format='JPEG')

@app.route('/map_generator', methods=['GET', 'POST'])
def map_generator():
    if request.method == 'POST':
        building = request.form['building']
        date_str = request.form['event_date']
        event_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Fetch events for the given building and date
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT Room, EmployerName, EventDate FROM InfoSessions WHERE Building = %s AND EventDate = %s", (building, event_date))
        info_sessions = cursor.fetchall()

        cursor.execute("SELECT Room, EmployerName, EventDate FROM Interviews WHERE Building = %s AND EventDate = %s", (building, event_date))
        interviews = cursor.fetchall()
        conn.close()

        # Merge both event lists
        events = info_sessions + interviews

        # Group events by floor
        from collections import defaultdict
        floor_map = defaultdict(list)
        for room, employer, _ in events:
            floor = int(room[0])
            floor_map[floor].append((room, employer))

        generated_paths = []
        for floor, floor_events in floor_map.items():
            map_path = f'static/maps/{building}_{floor}.png'
            out_path = f'static/generated/{building}_{floor}_{event_date}.jpg'

            annotate_map(map_path, floor_events, out_path, building)

            generated_paths.append(out_path)

        return render_template('map_result.html', image_paths=generated_paths, building=building, event_date=event_date)
    
    return render_template('map_form.html')


# Fun stuff
@app.route('/konami')
def konami():
    return render_template('konami.html')

@app.context_processor
def inject_background_image():
    return dict(background_image=get_season_background())

# Custom Error handlers
@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(404)
def internal_server_error(e):
    return render_template('404.html'), 404

@app.errorhandler(403)
def internal_server_error(e):
    return render_template('403.html'), 403

def archive_old_sessions():
    conn = get_connection()
    cursor = conn.cursor()

    today = date.today()

    # Fetch rows with past dates
    cursor.execute("""
        SELECT EventID, EmployerName, EventDate, StartTime, EndTime, Building, Room, MajorGroup, Food, Notes
        FROM InfoSessions
        WHERE EventDate < %s
    """, (today,))
    old_rows = cursor.fetchall()

    print(f"Archiving {len(old_rows)} old session(s)...")

    for row in old_rows:
        (
            event_id, employer_name, event_date,
            start_time, end_time, building, room,
            major_group, food, notes
        ) = row

        # Explicit type enforcement to avoid implicit conversion to 1900
        event_date = event_date if isinstance(event_date, date) else None
        start_time = start_time if isinstance(start_time, time) else (
            start_time.time() if isinstance(start_time, datetime) else None
        )
        end_time = end_time if isinstance(end_time, time) else (
            end_time.time() if isinstance(end_time, datetime) else None
        )

        # Insert into archive with NULL Attendees and Debrief
        cursor.execute("""
            INSERT INTO InfoSessionsArchive (
                EventID, EmployerName, EventDate, StartTime, EndTime,
                Building, Room, MajorGroup, Food, Notes,
                Attendees, Debrief
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
        """, (
            event_id, employer_name, event_date,
            start_time, end_time, building, room,
            major_group, food, notes
        ))

        # Delete from main table
        cursor.execute("DELETE FROM InfoSessions WHERE EventID = %s", (event_id,))

    conn.commit()
    conn.close()

if __name__ == '__main__':
    archive_old_sessions()  # Archive old sessions on startup
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)