# InterviewChatbot 🧑‍💻

InterviewChatbot is an AI-powered application designed to automate the initial technical screening process. It provides a Streamlit-based chatbot interface where candidates can input their details and tech stack. The application then uses the Groq API to generate relevant, open-ended technical questions and saves the candidate's answers to a MongoDB database.

## Features

* **Candidate Information:** Collects essential candidate details like name, email, phone, and experience.
* **Tech Stack Input:** Allows candidates to specify their programming languages, frameworks, databases, and tools.
* **AI-Powered Question Generation:** Connects to the Groq API (using the `llama-3.1-8b-instant` model) to generate 3-5 unique technical questions for each technology.
* **Interview Interface:** Presents the generated questions in a clean chat and form layout.
* **Database Storage:** Saves all candidate information and their answers securely to a MongoDB collection for review.

## Tech Stack

* **Frontend:** [Streamlit](https://streamlit.io/)
* **Backend Logic:** Python
* **AI/LLM:** [Groq](https://groq.com/)
* **Database:** [MongoDB](https://www.mongodb.com/) (using `pymongo`)
* **Dependencies:** `python-dotenv`, `streamlit`, `groq`, `pymongo`

## Setup and Installation

Follow these steps to get the application running locally.

### 1. Clone the Repository
```bash
git clone <your-repository-url>
cd <repository-folder>
````

### 2\. Create a Virtual Environment

It's highly recommended to use a virtual environment.

```bash
# For macOS/Linux
python3 -m venv venv
source venv/bin/activate

# For Windows
python -m venv venv
.\venv\Scripts\activate
```

### 3\. Install Dependencies

Install all required Python packages from `requirements.txt`:

```bash
pip install -r requirements.txt
```

### 4\. Set Up Environment Variables

The application requires API keys and database URIs to be set as environment variables. Create a file named `.env` in the root of your project directory.

**(Note:** The `.gitignore` file is already set up to ignore `.env`, so your keys won't be accidentally committed.**)**

Your `.env` file should look like this:

```
# Get your Groq API key from [https://console.groq.com/](https://console.groq.com/)
GROQ_API_KEY="gsk_YOUR_GROQ_API_KEY"

# Your MongoDB connection string.
MONGO_URI="mongodb://localhost:27017"
```

### 5\. Ensure MongoDB is Running

This application requires a running MongoDB instance. Make sure your MongoDB server is active and accessible via the `MONGO_URI` you provided in the `.env` file.

## How to Run

Once your environment is set up and MongoDB is running, you can start the Streamlit application:

```bash
streamlit run app.py
```

Open your web browser and navigate to the local URL provided in your terminal (usually `http://localhost:8501`).

## File Overview

  * **`app.py`**: The main Streamlit application. It handles the UI, session state, and multi-step form logic.
  * **`server.py`**: The backend module responsible for communicating with the Groq API and generating questions.
  * **`mongo.py`**: Contains all MongoDB logic, including the `MongoDB` client class and helper functions (`save_candidate_and_answers`) to interact with the database.
  * **`globals.py`**: A simple file used to share the global `techstack` list between modules.
  * **`requirements.txt`**: A list of all Python dependencies for the project.
  * **`.gitignore`**: Specifies files and directories that Git should ignore (like `.env` and `__pycache__`).

<!-- end list -->

```
```
