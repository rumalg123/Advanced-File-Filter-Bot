# Architecture Diagrams

This document captures the full architecture views for the Advanced File Filter Bot.

## 1. System Context

```mermaid
graph TB
    User[End User]
    Admin[Admin]
    Mod[Moderator]

    Telegram[Telegram Platform]
    Bot[Advanced File Filter Bot]

    Mongo[(MongoDB)]
    Redis[(Redis)]

    Support[Support and Index Request Chats]
    Ops[Health and Metrics Consumers]

    User --> Telegram
    Admin --> Telegram
    Mod --> Telegram

    Telegram --> Bot
    Bot --> Telegram

    Bot <--> Mongo
    Bot <--> Redis

    Bot --> Support
    Ops --> Bot
```

## 2. Runtime Container View

```mermaid
graph LR
    subgraph Runtime[Bot Runtime Process]
        Pyro[Pyrogram Client]
        HM[HandlerManager]
        HL[Handler Layer]
        SL[Service Layer]
        RL[Repository Layer]

        CFG[Config and Settings]
        API[TelegramAPIWrapper]
        LIM[RateLimiter]
        SEMA[SemaphoreManager]
        SES[UnifiedSessionManager]
        INV[CacheInvalidator]
    end

    Redis[(Redis)]
    Mongo[(MongoDB or Multi-DB Pools)]
    TG[Telegram API]

    Pyro --> HM --> HL --> SL --> RL
    HL --> API
    SL --> API

    SL --> LIM --> Redis
    SL --> SES --> Redis
    SL --> INV --> Redis
    RL --> INV

    RL --> Mongo
    API --> SEMA
    API --> TG

    CFG --> HL
    CFG --> SL
    CFG --> RL
```

## 3. Component Interaction Flow

```mermaid
graph TD
    U[Incoming Telegram Update]
    P[Pyrogram Dispatcher]
    H[Specific Handler]
    S[Domain Service]
    R[Repository]
    C[Redis Cache]
    D[MongoDB]

    U --> P --> H --> S --> R
    R --> C
    R --> D
    S --> C
    S --> P
```

## 4. Search and File Delivery Sequence

```mermaid
sequenceDiagram
    participant User
    participant Telegram
    participant SearchHandler
    participant FileAccessService
    participant RateLimiter
    participant UserRepo
    participant MediaRepo
    participant MultiDB
    participant Redis

    User->>Telegram: Send search query
    Telegram->>SearchHandler: Message update
    SearchHandler->>FileAccessService: search_files_with_access_check()
    FileAccessService->>RateLimiter: check_rate_limit(search)
    RateLimiter->>Redis: increment + TTL
    FileAccessService->>UserRepo: can_retrieve_file()
    FileAccessService->>MediaRepo: search_files()

    MediaRepo->>Redis: get(search cache key)
    alt Cache miss
        MediaRepo->>MultiDB: search_across_all_databases()
        MultiDB->>MultiDB: combine + sort + paginate
        MultiDB->>MediaRepo: merged results
        MediaRepo->>Redis: set(search cache)
    end

    SearchHandler->>Redis: store search session
    SearchHandler->>Telegram: send paginated results

    User->>Telegram: Click file callback
    Telegram->>SearchHandler: callback route
    SearchHandler->>FileAccessService: check_and_grant_access()
    FileAccessService->>UserRepo: validate access + increment
    SearchHandler->>Telegram: send_cached_media()
```

## 5. Send-All Flow With Atomic Quota Reservation

```mermaid
sequenceDiagram
    participant User
    participant FileCallback
    participant UserRepo
    participant Mongo
    participant TelegramAPI

    User->>FileCallback: Click Send All
    FileCallback->>UserRepo: reserve_quota_atomic(user, requested_count)
    UserRepo->>Mongo: find_one_and_update with guard condition

    alt Reservation failed
        UserRepo-->>FileCallback: fail + remaining quota message
        FileCallback-->>User: deny request
    else Reservation succeeded
        loop For each file
            FileCallback->>TelegramAPI: send_cached_media()
            TelegramAPI-->>FileCallback: success or failure
        end

        FileCallback->>UserRepo: release_quota(unused_count)
        UserRepo->>Mongo: decrement reserved count
        FileCallback-->>User: final transfer summary
    end
```

## 6. Channel Auto-Indexing Pipeline

```mermaid
sequenceDiagram
    participant Channel
    participant Telegram
    participant ChannelHandler
    participant Queue
    participant Worker
    participant MediaRepo
    participant MultiDB
    participant Mongo

    Channel->>Telegram: New media message
    Telegram->>ChannelHandler: handle_channel_media()
    ChannelHandler->>Queue: enqueue message

    Worker->>Queue: consume batch
    Worker->>Worker: extract media metadata
    Worker->>MediaRepo: save_media()
    MediaRepo->>MediaRepo: duplicate check
    MediaRepo->>MultiDB: get_optimal_write_database()
    MultiDB->>Mongo: insert document
    MediaRepo-->>Worker: saved or duplicate
    Worker-->>ChannelHandler: batch stats
```

## 7. Multi-Database Circuit Breaker State Model

```mermaid
stateDiagram-v2
    [*] --> CLOSED

    CLOSED --> OPEN: failures >= max_failures
    OPEN --> HALF_OPEN: recovery timeout elapsed

    HALF_OPEN --> CLOSED: successful probe
    HALF_OPEN --> OPEN: probe failure

    OPEN --> OPEN: reject requests while timeout active
    CLOSED --> CLOSED: normal successful operations
```

## 8. Data Model (Core Collections)

```mermaid
erDiagram
    USERS {
        int _id
        string name
        string status
        bool is_premium
        datetime premium_expiry_date
        int daily_retrieval_count
        int daily_request_count
        int warning_count
    }

    MEDIA_FILES {
        string _id
        string file_unique_id
        string file_name
        int file_size
        string file_type
        string caption
        datetime indexed_at
        string resolution
        string season
        string episode
        int channel_id
    }

    INDEXED_CHANNELS {
        int _id
        string channel_username
        bool enabled
        int indexed_count
        datetime last_indexed_at
    }

    CONNECTIONS {
        string _id
        string active_group
        string group_details
        datetime updated_at
    }

    BATCH_LINKS {
        string _id
        int source_chat_id
        int from_msg_id
        int to_msg_id
        bool protected
        bool premium_only
        int created_by
        datetime expires_at
    }

    BOT_SETTINGS {
        string _id
        any value
        string value_type
        any default_value
        datetime updated_at
    }

    INDEXED_CHANNELS ||--o{ MEDIA_FILES : indexes
    USERS ||--o{ BATCH_LINKS : creates
    USERS ||--o{ CONNECTIONS : owns
```

## 9. Deployment Topology (Docker-Oriented)

```mermaid
graph LR
    subgraph TelegramCloud[Telegram Cloud]
        TG[Telegram API]
    end

    subgraph Host[Runtime Host]
        subgraph Compose[Docker Compose]
            BOT[Bot Container]
            REDIS[Redis Container]
        end

        H[HTTP Endpoints /health /metrics]
    end

    MONGO[(MongoDB Local or Atlas)]
    ADMIN[Admin Operators]

    TG <--> BOT
    BOT <--> REDIS
    BOT <--> MONGO

    ADMIN --> BOT
    ADMIN --> H
```

## Notes

- Diagrams are derived directly from the current code structure in `bot.py`, `core/*`, `handlers/*`, and `repositories/*`.
- For portfolio presentation, you can reuse these diagrams as-is in case studies or interview walk-throughs.
