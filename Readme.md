# Com 503

## Description

This project is a Python application that can be run using Docker.

## Prerequisites

- Docker installed on your machine

## Installation

1. Clone the repository to your local machine:
    ```sh
    git clone <repository-url>
    cd <repository-directory>
    ```

2. Build the Docker image:
    ```sh
    docker build -t com503-app .
    ```

## Running the Application

1. Run the Docker container:
    ```sh
    docker run -p 5000:5000 com503-app
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

## License

This project is licensed under the MIT License.
