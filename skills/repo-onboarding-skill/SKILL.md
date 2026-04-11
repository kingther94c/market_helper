---
name: repo-onboarding-skill
description: 新开线程时自动做：读 README / DEV_DOCS / AGENTS.md / pyproject.toml / 目录树，输出：项目目标 当前模块边界 常用命令 已知约束 下一步建议
file: /Users/kelvin/git_projects/market_helper/skills/repo-onboarding-skill/SKILL.md
---

# Repo Onboarding Skill

## Overview
This skill automates the process of onboarding new team members or sessions to a repository by automatically reading key documentation files and the directory structure, then generating a structured overview of the project.

## Trigger
Automatically activates when starting a new thread/session in the repository context.

## Functionality
The skill performs the following actions:

1. **Reads Key Files**:
   - README.md
   - DEV_DOCS/ directory contents
   - AGENTS.md
   - pyproject.toml
   - Project directory tree

2. **Generates Structured Output**:
   - **项目目标 (Project Goals)**: Extracts and summarizes the project's objectives and purpose
   - **当前模块边界 (Current Module Boundaries)**: Identifies the main modules and their responsibilities
   - **常用命令 (Common Commands)**: Lists frequently used commands for development, testing, and deployment
   - **已知约束 (Known Constraints)**: Documents current limitations, dependencies, or restrictions
   - **下一步建议 (Next Steps Recommendations)**: Provides suggestions for immediate next actions or improvements

## Implementation
The skill uses file reading tools to access the specified files and directory structure, then applies natural language processing to extract and organize the relevant information into the structured output format.

## Usage
This skill is intended to be invoked automatically when a new conversation thread begins in a repository context, providing immediate context and orientation for developers joining the project.

## Dependencies
- Access to repository files
- File reading capabilities
- Natural language processing for content extraction

## Output Format
The skill outputs information in a clear, structured format with Chinese labels as specified, making it accessible for international teams while maintaining the requested terminology.