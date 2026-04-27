import os
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Le bot est en ligne !"

def run():
    port = int(os.environ.get("PORT", 10000))
    # On ajoute threaded=True pour plus de sécurité
    app.run(host='0.0.0.0', port=port, threaded=True)

def keep_alive():
    # On s'assure que le thread est bien lancé en arrière-plan
    t = Thread(target=run)
    t.start()
    print("Serveur de monitoring lancé !")

