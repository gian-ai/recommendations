# System Design Documentation

The idea of this project is to learn the fundamental principles that make Apache Kafka relevant today.

## Performance Metrics
4 ms / request:
* 1 message queue server process
* 1 agent process, predicting with random.choice
* Tested over 5 iterations of 10 clients concurrently making 100 requests
* Hardware: MBP M1 16GB RAM, Sequoia 15.3.2

## External Libraries
* Pydantic

## System Design Features
* Asynchronous Message Queue
* Topic-Based Pub/Sub
* TCP Websocket Networking
* Schema Validation and Serialization
* Query and Prediction Caching
* Retry Mechanisms
* Error and Exception Handling

## Project Structure

```
actors/
├── agent.py     # Responsible for lookup and prediction
├── client.py    # Responsible for representing user query
└── server.py    # Responsible for orchestration and bookkeeping

communicate/
├── mq.py        # Async Topic-Based Pub/Sub Message Queue & Client
└── stub.py      # Communication Protocol / Interfaces

data/
├── store.py     # Serialization and Logging
└── logs/
    ├── query.txt    # Chronological Query Log
    └── solve.txt    # Chronological Solution Log


## Recommendations
For optimal use of this framework:
1. Follow the established design philosophy
2. Maintain the separation of concerns between actors
3. Utilize the asynchronous message queue for efficient communication
4. Implement proper error handling throughout your implementation
5. Make use of schema validation to ensure data integrity