-- ============================================================
--  Placement Prediction System  –  Database Setup
--  Run once to create the database and table.
-- ============================================================

CREATE DATABASE IF NOT EXISTS placement_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE placement_db;

CREATE TABLE IF NOT EXISTS predictions (
    id                      INT           AUTO_INCREMENT PRIMARY KEY,
    student_name            VARCHAR(120)  NOT NULL,
    student_class           VARCHAR(30)   NOT NULL,

    -- Raw features (same order as model input)
    cgpa                    FLOAT         NOT NULL,
    internships             FLOAT         NOT NULL,
    projects                FLOAT         NOT NULL,
    coding_skills           FLOAT         NOT NULL,
    communication_skills    FLOAT         NOT NULL,
    aptitude_test_score     FLOAT         NOT NULL,
    backlogs                FLOAT         NOT NULL,
    degree                  VARCHAR(20)   NOT NULL,
    gender                  VARCHAR(10)   NOT NULL,

    -- Engineered features
    avg_score               FLOAT         NOT NULL,
    total_skills            FLOAT         NOT NULL,
    is_weak                 TINYINT(1)    NOT NULL,

    -- Prediction output
    prediction_result       VARCHAR(20)   NOT NULL,
    probability             FLOAT         NOT NULL,

    -- Metadata
    created_at              DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_class  (student_class),
    INDEX idx_result (prediction_result),
    INDEX idx_time   (created_at)
);
