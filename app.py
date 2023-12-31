from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_cors import cross_origin
from langchain.document_loaders import PyPDFLoader
from langchain.llms import OpenAI
from langchain.chains import RetrievalQA
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma
import tempfile
import traceback
import time
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, firestore, auth
from flask import Response
from time import sleep
from flask import Flask, Response, request
import requests
import threading
import time
from datetime import datetime
import os

current_dir = os.path.dirname(os.path.realpath(__file__))
json_path = os.path.join(current_dir, 'pdf-chat-cc707-firebase-adminsdk-sqzre-0801f75402.json')


cred = credentials.Certificate(json_path)
firebase_admin.initialize_app(cred)

db = firestore.client()
import stripe

app = Flask(__name__)
app.config['CORS_HEADERS'] = ['Content-Type', 'Authorization']
app.config['CORS_ALLOW_ALL_ORIGINS'] = True
CORS(app, resources={r"/api/*": {"origins": "https://docchat.in"}})

current_response = None
qa = {}
stripe.api_key = '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'

OPENAI_KEY = os.getenv('OPENAI_KEY')

def authenticate_request(request):
    id_token = request.headers['Authorization'].split(' ').pop()
    decoded_token = auth.verify_id_token(id_token)
    uid = decoded_token['uid']
    return uid

@app.route('/api/process-pdf', methods=['POST'])
def process_pdf():
    global qa  # Declare the 'qa' object as global

    if 'pdf' not in request.files:
        return jsonify({"error": "No PDF file provided"}), 400

    file = request.files['pdf']
    file_name = secure_filename(file.filename)

    print(file_name)

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.write(file.read())
    temp_file.close()

    try:
        loader = PyPDFLoader(temp_file.name)
        documents = loader.load()

        text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
        texts = text_splitter.split_documents(documents)
        embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_KEY)
        db = Chroma.from_documents(texts, embeddings)
        retriever = db.as_retriever(search_type="similarity", search_kwargs={"k":1})
        qa[file_name] = RetrievalQA.from_chain_type(
            llm=OpenAI(openai_api_key=OPENAI_KEY), chain_type="stuff", retriever=retriever, return_source_documents=True)
        return jsonify({"message": "Successfully Uploaded"})

    except Exception as e:
        print("Error processing PDF:", e)
        return jsonify({"error": "Error processing PDF file"}), 500

# @app.route('/api/chat', methods=['POST'])
# def chat():
#     global qa  # Declare the 'qa' object as global

#     uid = authenticate_request(request)
#     message = request.json.get('message')
#     file_name = request.json.get('backendFile')
#     save_chat_message({'text':message,'type':'user'}, file_name, uid)
#     if not message:
#         return jsonify({"error": "No message provided"}), 400

#     try:
#         # Process the message and get a response from the backend
#         result = qa[file_name]({"query": message})
#         save_chat_message({'text':result['result'],'type':'backend'}, file_name, uid)

#         # Convert the result to a JSON serializable format
#         def generate_response(result):
#             for word in result['result'].split():
#                 print(word)
#                 yield f"data: {word}\n\n"
#                 sleep(0.5)  # delay for demonstration, you can adjust or remove

#         return Response(generate_response(result), mimetype='text/event-stream')
#     except Exception as e:
#         print("Error processing message:", e)
#         print(traceback.format_exc())  # Add this line to print the traceback

#         return jsonify({"error": "Error processing message"}), 500
    
response_generator = None
lock = threading.Lock()

@app.route('/api/chat', methods=['POST'])
def chat():
    uid = authenticate_request(request)
    message = request.json.get('message')
    file_name = request.json.get('backendFile')
    save_chat_message({'text':message,'type':'user'}, file_name, uid)
    global response_generator 
    message = request.json.get('message')
    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        # Process the message and get a response from the backend
        result =qa[file_name]({"query": message})
        save_chat_message({'text':result['result'],'type':'backend'}, file_name, uid)

        # Convert the result to a JSON serializable format
        def generate_response(result):
            for word in result['result'].split():
                print(word)
                yield word
                time.sleep(0.2)  # delay for demonstration, you can adjust or remove

        with lock:
            response_generator = generate_response(result)

        return {"status": "message received"}
    except Exception as e:
        print("Error processing message:", e)
        print(traceback.format_exc())  # Add this line to print the traceback

        return jsonify({"error": "Error processing message"}), 500
    
@app.route("/pdf", methods=['GET'])
def get_pdf():
    url = request.args.get("url", default = None, type = str)
    if url is None:
        return jsonify(error="Missing URL parameter"), 400

    try:
        response = requests.get(url)
        response.raise_for_status()
        return Response(response.content, mimetype='application/pdf')
    except requests.exceptions.RequestException as err:
        print ("Error fetching PDF", err)
        return jsonify(error="Failed to fetch PDF"), 500

@app.route('/api/chat/stream', methods=['GET'])
def chat_stream():
    def event_stream():
        global response_generator
        while True:
            with lock:
                word = next(response_generator, None)
            if word is None:
                break
            yield f"data: {word}\n\n"
    return Response(event_stream(), mimetype="text/event-stream")

@app.route('/api/delete-conversation', methods=['POST'])
def delete_conversation():
    global qa  # Declare the 'qa' object as global

    file_name = request.json.get('pdf_file')
    if not file_name:
        return jsonify({"error": "No file name provided"}), 400

    try:
        # Delete the corresponding key from the 'qa' object
        del qa[file_name]
        print(qa)
        return jsonify({"message": f"Successfully deleted conversation for {file_name}"})
    except KeyError:
        return jsonify({"error": f"Conversation for {file_name} not found"}), 404
    except Exception as e:
        print("Error deleting conversation:", e)
        return jsonify({"error": "Error deleting conversation"}), 500

def save_chat_message(message, filename, uid):
    conversations_ref = db.collection('users').document(uid).collection('conversations')
    matching_conversations = conversations_ref.where('fileName', '==', filename).limit(1).stream()

    conversation_id = None
    for doc in matching_conversations:
        conversation_id = doc.id
        break

    if conversation_id is None:
        # create a new conversation document
        new_conversation_ref = conversations_ref.document()
        new_conversation_ref.set({
            'fileName': filename
        })
        conversation_id = new_conversation_ref.id

    messages_ref = conversations_ref.document(conversation_id).collection('messages')
    messages_ref.add({
        'text': message['text'],
        'sender': message['type'],
        'timestamp': datetime.now()
    })

@app.route('/api/conversations', methods=['GET'])
def fetch_conversations():
    # Extract user token from the request header
    uid = authenticate_request(request)
    conversations_ref = db.collection('users').document(uid).collection('conversations')

    try:
        # Get all the conversation documents
        conversations_snapshot = conversations_ref.get()
        conversations_data = [{'id': doc.id, **doc.to_dict()} for doc in conversations_snapshot]
        # Get the latest message of each conversation
        conversations_with_latest_message = []
        for conversation in conversations_data:
            messages_ref = conversations_ref.document(conversation['id']).collection('messages')
            last_message_snapshot = messages_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(1).get()
            last_message = last_message_snapshot[0].to_dict()
            
            # Convert the timestamp to a datetime object, then to a formatted string
            formatted_timestamp = last_message['timestamp'].strftime('%B %d, %Y at %I:%M:%S %p %Z')

            # Append the conversation data with the latest message
            conversations_with_latest_message.append({
                'id': conversation['id'],
                'fileName': conversation['fileName'],
                'latestMessage': {
                    'text': last_message['text'],
                    'sender': last_message['sender'],
                    'timestamp': formatted_timestamp,
                },
            })

        sorted_conversations = sorted(conversations_with_latest_message, key=lambda k: k['latestMessage']['timestamp'], reverse=True)
        return jsonify(sorted_conversations), 200
    except Exception as e:
        print(str(e))
        return jsonify({'error': 'Conversations not found'}), 404

@app.route('/api/conversations/messages', methods=['GET'])
def get_conversation_messages():
    uid = request.args.get('uid')
    fileName = request.args.get('fileName')
    conversations_ref = db.collection('users').document(uid).collection('conversations')

    # Query for the conversation with the given fileName
    conversations = conversations_ref.where('fileName', '==', fileName).get()

    if len(conversations) == 0:
        return jsonify({'error': 'No conversation found for the given file name.'}), 404

    conversation = conversations[0]

    # Get the messages for this conversation
    messages_ref = conversations_ref.document(conversation.id).collection('messages')
    messages_snapshot = messages_ref.get()

    # Convert the messages to a list of dictionaries
    messages = [message.to_dict() for message in messages_snapshot]

    # Sort the messages by timestamp
    messages.sort(key=lambda message: message['timestamp'])

    # Format the messages for the response
    formatted_messages = [
        {
            'type': message['sender'],
            'text': message['text'],
            'timestamp': message['timestamp'].strftime('%B %d, %Y at %I:%M:%S %p %Z'),
        }
        for message in messages
    ]

    return jsonify(formatted_messages), 200
    
@app.route('/create-checkout-session', methods=['POST'])
@cross_origin(origin='*', headers=['Content- Type', 'Authorization'])
def create_checkout_session():
    data = request.get_json()
    uid = data['uid']  # Here is where you extract the uid
    session = stripe.checkout.Session.create(
      payment_method_types=['card'],
      line_items=[{
        'price': 'price_1NOFSSSDnmZGzrWBoI5UWjwJ',  # replace with the actual price ID from Stripe Dashboard
        'quantity': 1,
      }],
      mode='subscription',
      success_url='https://docchat.in/',
      cancel_url='https://docchat.in/landing',
      client_reference_id=uid,
    )

    return jsonify(id=session.id)

@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = 'whsec_QF3veDvW6IevNmpMNCzXsso8z6P6H57w'  # replace with your endpoint secret

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        # Invalid payload
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return 'Invalid signature', 400

    # Handle the checkout.session.completed event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']

        # client_reference_id is the uid of the user
        uid = session['client_reference_id']

        # Update the Firestore database
        user_ref = db.collection('users').document(uid)
        user_ref.update({
            'isSubscribed': True
        })

    return '', 200

@app.route('/api/user/subscription', methods=['GET'])
def get_user_subscription():
    try:
        uid = authenticate_request(request)
        user_ref = db.collection('users').document(uid)
        user = user_ref.get()
        if user.exists:
            return jsonify({'subscribed': user.to_dict().get('subscribed', False)}), 200
        else:
            return jsonify({'error': 'No such user exists.'}), 404
    except Exception as e:
        print(f"Error getting user's subscription status: {e}")
        return jsonify({'error': 'Error getting user subscription status.'}), 500



if __name__ == "__main__":
    app.run(debug=True)
