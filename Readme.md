# Com 503

## Description

This project is a Python application that can be run using Docker. It provides weather warnings and user preferences management through a web interface.

## Prerequisites

- Docker installed on your machine
- Docker Compose installed on your machine

## Installation

1. Clone the repository to your local machine:
    ```sh
    git clone <repository-url>
    cd <repository-directory>
    ```

2. Copy the example environment file and update it with your credentials:
    ```sh
    cp .env.example .env
    ```

3. Update the `.env` file with your Google OAuth credentials and MongoDB credentials.

## Running the Application

1. Start the application using Docker Compose:
    ```sh
    docker-compose up --build
    ```

2. The application will be accessible at `http://localhost:5000`.

## Development

If you want to develop and test the application locally without Docker, follow these steps:

1. Install Python 3.9 and `pip` on your machine.

2. Install the required dependencies:
    ```sh
    pip install -r requirements.txt
    ```

3. Run the application:
    ```sh
    python app/app.py
    ```

4. The application will be accessible at `http://localhost:5000`.

## Excluding Logs from Git

To exclude the `logs` folder from being tracked by Git, add the following line to your `.gitignore` file:
```plaintext
logs/
