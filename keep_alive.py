import os
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Le bot est en ligne !"

def run():
    # Render utilise le port 10000 par défaut
    # Render utilise souvent le port 10000, 
    # mais il est plus sûr d'utiliser la variable d'environnement PORT
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()
