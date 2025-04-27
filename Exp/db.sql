CREATE DATABASE resume_parser;
USE resume_parser;

CREATE TABLE resumes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    linkedin VARCHAR(255),
    job_title VARCHAR(255),
    skills TEXT,
    experience TEXT,
    education TEXT,
    certifications TEXT,
    projects TEXT,
    location VARCHAR(255),
    industry_domain VARCHAR(255)
);
