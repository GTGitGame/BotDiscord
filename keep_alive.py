import os
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Le bot est en ligne !"

def run():
    # Utilise le port 10000 exigé par Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    # C'EST CETTE LIGNE QUI DÉBLOQUE TOUT :
    # On lance 'run' dans un thread séparé pour libérer le script principal
    t = Thread(target=run)
    t.start()
