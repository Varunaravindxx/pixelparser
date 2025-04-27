from flask import Flask, request, jsonify, render_template
import os
import docx
import PyPDF2
import requests
import json
import mysql.connector
import re  # For regex extraction
import hashlib  # New: for generating cache hash

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads/'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
supported_formats = ['.docx', '.pdf']
groq_api_key = "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"
groq_endpoint = "https://api.groq.com/openai/v1/chat/completions"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db_config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '',
    'database': 'resume_parser'
}

# New: Cache utility function
def generate_hash(text1, text2):
    combined = text1.strip() + text2.strip()
    return hashlib.md5(combined.encode()).hexdigest()

def extract_text_from_file(file):
    filename = file.filename
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)
    text = ''
    
    if filename.endswith('.docx'):
        doc = docx.Document(file_path)
        text = '\n'.join([para.text for para in doc.paragraphs])
    elif filename.endswith('.pdf'):
        with open(file_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            for page in pdf_reader.pages:
                text += page.extract_text() or ''
    
    return text

def save_to_database(data):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()

        query = """
        INSERT INTO resumes (
            name, email, phone, linkedin, job_title,
            skills, experience, education,
            certifications, projects, location, industry_domain
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        message_content = data['choices'][0]['message']['content']

        # Extract the JSON object using regex
        json_match = re.search(r'\{.*\}', message_content, re.DOTALL)
        if not json_match:
            raise ValueError("No valid JSON object found in the response.")

        json_data = json.loads(json_match.group(0))  # Parse the JSON object

        values = (
            json_data.get("Name"),
            json_data.get("Email"),
            json_data.get("Phone"),
            json_data.get("LinkedIn"),
            json_data.get("Job Title"),
            json_data.get("Skills"),
            json_data.get("Experience"),
            json_data.get("Education"),
            json_data.get("Certifications"),
            json_data.get("Projects"),
            json_data.get("Location"),
            json_data.get("Industry Domain")
        )

        print("Saving to database:", values)
        cursor.execute(query, values)
        connection.commit()
        cursor.close()
        connection.close()
        print("Data successfully saved to the database.")
    except mysql.connector.Error as err:
        print(f"Database Error: {err}")
    except (json.JSONDecodeError, ValueError) as err:
        print(f"JSON Parsing Error: {err}")

def parse_resume_with_groq(text):
    prompt = f"""
    Extract the following fields from the resume text:
    - Name
    - Email
    - Phone
    - LinkedIn
    - Job Title
    - Skills
    - Experience
    - Education
    - Certifications
    - Projects
    - Location
    - Industry Domain

    Resume Text:
    {text}

    Return the result in the following JSON format:
    {{
        "Name": "John Doe",
        "Email": "john@example.com",
        "Phone": "+91 9876543210",
        "LinkedIn": "https://linkedin.com/in/johndoe",
        "Job Title": "Software Developer",
        "Skills": "Python, Flask, SQL",
        "Experience": "3 years in web development",
        "Education": "B.Tech in Computer Science",
        "Certifications": "AWS Certified Developer",
        "Projects": "Resume Parser, Chatbot",
        "Location": "Chennai, India",
        "Industry Domain": "IT Services"
    }}
    """

    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "deepseek-r1-distill-llama-70b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0  # Updated: deterministic output
    }

    try:
        response = requests.post(groq_endpoint, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error calling Groq API: {e}")
        return {"error": str(e)}

# --- New function to match resume skills with job description with detailed analysis ---
def match_resume_job_desc(skills, job_desc_text):
    prompt = f"""
    You are a resume-job analyzer.

    Given the following job description:
    {job_desc_text}

    And the candidate profile:
    Skills: {skills}
    (Note: The candidate's projects and experience are also available in the resume.)

    Evaluate the match between the candidate's skills and the job requirements.
    Perform a deep analysis including:
    - A match score (from 0 to 100),
    - A list of matched skills,
    - A list of lacking but necessary skills,
    - A brief reasoning on the candidate's overall fit for the job,
    - Evaluation of whether the candidate's projects are relevant to the job description.

    Return the result in JSON format as:
    {{
       "score": 82,
       "matched": ["Python", "Flask"],
       "lacking": ["Docker", "CI/CD"],
       "fit_reasoning": "The candidate has strong web backend skills relevant for the role but lacks DevOps experience.",
       "project_relevance": "The candidate built a resume parser and a chatbot, which aligns well with the role's requirement for automation and intelligent systems."
    }}
    """
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-r1-distill-llama-70b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0  # Updated: ensure consistency on repeated requests
    }
    try:
        response = requests.post(groq_endpoint, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error calling Groq API for matching: {e}")
        return {"error": str(e)}

# --- New endpoint to process both resume and job description ---
@app.route('/match', methods=['POST'])
def match():
    # Validate that required files are provided
    if 'job_description' not in request.files or 'resume' not in request.files:
        return jsonify({'error': 'Both job description and resume files are required.'}), 400

    job_desc_file = request.files['job_description']
    resume_file = request.files['resume']

    if job_desc_file.filename == '' or resume_file.filename == '':
        return jsonify({'error': 'One or both files have not been selected.'}), 400

    if not (any(job_desc_file.filename.endswith(ext) for ext in supported_formats) and 
            any(resume_file.filename.endswith(ext) for ext in supported_formats)):
        return jsonify({'error': 'Unsupported file type for one or both files.'}), 400

    # Extract text from the files
    job_desc_text = extract_text_from_file(job_desc_file)
    resume_text = extract_text_from_file(resume_file)

    # Parse the resume using the existing function
    resume_result = parse_resume_with_groq(resume_text)
    if 'error' in resume_result:
        return jsonify({'error': 'Failed to process resume', 'details': resume_result.get('error')}), 500

    # Save the parsed resume data into the database using the existing function
    save_to_database(resume_result)
    
    # Extract the "Skills" field from the parsed resume
    try:
        message_content = resume_result['choices'][0]['message']['content']
        json_match = re.search(r'\{.*\}', message_content, re.DOTALL)
        if not json_match:
            raise ValueError("No valid JSON object found in the resume parsing response.")
        resume_json = json.loads(json_match.group(0))
        skills = resume_json.get("Skills")
    except Exception as e:
        return jsonify({'error': 'Error extracting skills from resume', 'details': str(e)}), 500

    # --- Generate a hash for caching the result (static accuracy for same inputs) ---
    hash_key = generate_hash(resume_text, job_desc_text)
    cache_path = os.path.join(UPLOAD_FOLDER, f"{hash_key}.json")

    # If cached result exists, use it, otherwise compute and cache it
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            match_json = json.load(f)
    else:
        # Use the extracted skills and the job description to perform matching
        match_result = match_resume_job_desc(skills, job_desc_text)
        if 'error' in match_result:
            return jsonify({'error': 'Failed to match resume with job description', 'details': match_result.get('error')}), 500

        try:
            message_content = match_result['choices'][0]['message']['content']
            json_match = re.search(r'\{.*\}', message_content, re.DOTALL)
            if not json_match:
                raise ValueError("No valid JSON object found in the job matching response.")
            match_json = json.loads(json_match.group(0))
        except Exception as e:
            return jsonify({'error': 'Error extracting match data', 'details': str(e)}), 500

        # Cache the computed matching result for consistency
        with open(cache_path, "w") as f:
            json.dump(match_json, f)

    # --- Generate sample heatmap data for demonstration ---
    heatmapData = []
    if 'matched' in match_json:
        for skill in match_json.get("matched"):
            # For demonstration, assign a fixed score (modify as needed)
            heatmapData.append({"skill": skill, "score": 80})
    match_json["heatmapData"] = heatmapData

    return jsonify(match_json), 200

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload_resume', methods=['POST'])
def upload_resume():
    if 'resume' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['resume']

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and any(file.filename.endswith(ext) for ext in supported_formats):
        extracted_text = extract_text_from_file(file)
        result = parse_resume_with_groq(extracted_text)
        if 'error' not in result:
            save_to_database(result)
            return jsonify({'message': 'Resume processed and saved!', 'data': result}), 200
        else:
            return jsonify({'error': 'Failed to process resume', 'details': result.get('error')}), 500
    
    return jsonify({'error': 'Unsupported file type'}), 400

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
