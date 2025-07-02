from flask import Flask, render_template

app = Flask(__name__)

@app.route('/editor')
def editor():
    columns = ['id', 'name', 'email', 'age']
    return render_template('editor.html', columns=columns)

if __name__ == '__main__':
    app.run(debug=True)
