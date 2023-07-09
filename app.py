from flask import Flask, request, jsonify
from flask_cors import CORS
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
from datetime import datetime

cred = credentials.Certificate('/Users/kaivan/pdf-chat-backend/backend/pdf-chat-cc707-firebase-adminsdk-sqzre-0801f75402.json')
firebase_admin.initialize_app(cred)

db = firestore.client()
import stripe

app = Flask(__name__)
CORS(app)

qa = {}
stripe.api_key = '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'

def authenticate_request(request):
    id_token = request.headers['Authorization'].split(' ').pop()
    decoded_token = auth.verify_id_token(id_token)
    uid = decoded_token['uid']
    return uid

@app.route('/')
def hello_world():
    return "Hello world"

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
        embeddings = OpenAIEmbeddings(openai_api_key="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")
        db = Chroma.from_documents(texts, embeddings)
        retriever = db.as_retriever(search_type="similarity", search_kwargs={"k":1})
        qa[file_name] = RetrievalQA.from_chain_type(
            llm=OpenAI(openai_api_key="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"), chain_type="stuff", retriever=retriever, return_source_documents=True)
        return jsonify({"message": "Successfully Uploaded"})

    except Exception as e:
        print("Error processing PDF:", e)
        return jsonify({"error": "Error processing PDF file"}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    global qa  # Declare the 'qa' object as global
    print(qa)

    uid = authenticate_request(request)
    message = request.json.get('message')
    file_name = request.json.get('backendFile')
    save_chat_message({'text':message,'type':'user'}, file_name, uid)
    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        # Process the message and get a response from the backend
        result = qa[file_name]({"query": message})
        save_chat_message({'text':result['result'],'type':'backend'}, file_name, uid)

        # Convert the result to a JSON serializable format
        json_result = {
            "query": result['query'],
            "answer": result['result']
        }
        return json_result
    except Exception as e:
        print("Error processing message:", e)
        print(traceback.format_exc())  # Add this line to print the traceback

        return jsonify({"error": "Error processing message"}), 500

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
      success_url='http://localhost:3000/',
      cancel_url='http://localhost:3000/pricing',
      client_reference_id=uid,
    )

    return jsonify(id=session.id)

@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = 'your_endpoint_secret'  # replace with your endpoint secret

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
    print(event)
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


if __name__ == "__main__":
    app.run(debug=True)
