"""Financial Optimization Orchestrator Agent.

This agent demonstrates the orchestrator-workers pattern using Claude Agent SDK.
It fetches financial data from MCP servers and coordinates specialized sub-agents
to provide comprehensive financial optimization recommendations.
"""

import argparse
import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AgentDefinition,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    PermissionResultAllow,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,p%(process)s,{%(filename)s:%(lineno)d},%(levelname)s,%(message)s",
)

logger = logging.getLogger(__name__)


DATA_DIR: Path = Path(__file__).parent.parent / "data"
RAW_DATA_DIR: Path = DATA_DIR / "raw_data"
AGENT_OUTPUTS_DIR: Path = DATA_DIR / "agent_outputs"


def _load_prompt(filename: str) -> str:
    """Load prompt from prompts directory."""
    prompt_path = Path(__file__).parent / "prompts" / filename
    return prompt_path.read_text()


async def _auto_approve_all(
    tool_name: str,
    input_data: dict,
    context
) -> PermissionResultAllow:
    """Auto-approve all tools without prompting."""
    logger.debug(f"Auto-approving tool: {tool_name}")
    return PermissionResultAllow()


def _ensure_directories():
    """Ensure all required directories exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    AGENT_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _save_json(
    data: dict,
    filename: str
):
    """Save data to JSON file."""
    filepath = RAW_DATA_DIR / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Saved data to {filepath}")


def _detect_subscriptions(
    bank_transactions: list[dict],
    credit_card_transactions: list[dict]
) -> list[dict]:
    """Detect subscription services from recurring transactions.

    TODO: Implement logic to:
    1. Filter transactions marked as recurring
    2. Identify subscription patterns (monthly charges)
    3. Categorize by service type
    4. Calculate total monthly subscription cost

    Args:
        bank_transactions: List of bank transaction dicts
        credit_card_transactions: List of credit card transaction dicts

    Returns:
        List of subscription dictionaries with service name, amount, frequency
    """
    subscriptions = []

    # TODO: Implement subscription detection logic
    # Hint: Look for transactions with recurring=True
    # Hint: Subscriptions are typically negative amounts (outflows)
    seen = set()

    all_transactions = [
        (t, "bank") for t in bank_transactions
    ] + [
        (t, "credit_card") for t in credit_card_transactions
    ]

    for transaction, _ in all_transactions:
        # Filter transactions marked as recurring
        if not transaction.get("recurring", False):
            continue
        # Subscriptions are outflows (negative amounts)
        if transaction.get("amount", 0) >= 0:
            continue

        # Deduplicate by description + amount
        key = (transaction.get("description", "").strip().lower(), transaction.get("amount"))
        if key in seen:
            continue
        seen.add(key)

        subscriptions.append({
            "service": transaction.get("description", "Unknown"),
            "amount": abs(transaction.get("amount", 0)),
            "frequency": "monthly",
        })

    total_monthly = sum(s["amount"] for s in subscriptions)
    logger.info(f"Total monthly subscription cost: ${total_monthly:.2f}")

    return subscriptions


async def _fetch_financial_data(
    username: str,
    start_date: str,
    end_date: str
) -> tuple[dict, dict]:
    """Fetch data from Bank and Credit Card MCP servers.

    TODO: Implement MCP server connections using Claude Agent SDK
    1. Configure MCP server connections (ports 5001, 5002)
    2. Call get_bank_transactions tool
    3. Call get_credit_card_transactions tool
    4. Save raw data to files

    Args:
        username: Username for the account
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Tuple of (bank_data, credit_card_data) dictionaries
    """
    logger.info(f"Fetching financial data for {username} from {start_date} to {end_date}")

    # TODO: Configure and connect to MCP servers
    # Example MCP configuration (keys must match FastMCP server names exactly):
    # mcp_servers = {
    #     "Bank Account Server": {  # Must match FastMCP("Bank Account Server")
    #         "type": "sse",
    #         "url": "http://127.0.0.1:5001"
    #     },
    #     "Credit Card Server": {  # Must match FastMCP("Credit Card Server")
    #         "type": "sse",
    #         "url": "http://127.0.0.1:5002"
    #     }
    # }

    # TODO: Call MCP tools to fetch data
    mcp_servers = {
        "Bank Account Server": {
            "type": "http",
            "url": "http://127.0.0.1:5001/mcp"
        },
        "Credit Card Server": {
            "type": "http",
            "url": "http://127.0.0.1:5002/mcp"
        }
    }

    working_dir = Path(__file__).parent.parent

    fetch_options = ClaudeAgentOptions(
        model="haiku",
        system_prompt="You are a data fetching agent. Call the requested MCP tools and output ONLY a valid JSON object with keys 'bank_data' and 'credit_card_data' containing the raw tool results. No explanation, no markdown, just JSON.",
        mcp_servers=mcp_servers,
        can_use_tool=_auto_approve_all,
        cwd=str(working_dir)
    )

    bank_data = {}
    credit_card_data = {}

    async with ClaudeSDKClient(options=fetch_options) as client:
        fetch_prompt = (
            f'Call get_bank_transactions(username="{username}", start_date="{start_date}", end_date="{end_date}") '
            f'and get_credit_card_transactions(username="{username}", start_date="{start_date}", end_date="{end_date}"). '
            'Output the results as a JSON object: {"bank_data": <bank result>, "credit_card_data": <credit card result>}'
        )
        await client.query(fetch_prompt)

        raw_text = ""
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        raw_text += block.text
            elif isinstance(message, ResultMessage):
                break

    try:
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            results = json.loads(match.group())
            bank_data = results.get("bank_data", {})
            credit_card_data = results.get("credit_card_data", {})
            logger.info(f"Fetched {len(bank_data.get('transactions', []))} bank transactions")
            logger.info(f"Fetched {len(credit_card_data.get('transactions', []))} credit card transactions")
        else:
            logger.error(f"No JSON found in fetch response: {raw_text[:200]}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse fetch results as JSON: {e}\nRaw: {raw_text[:200]}")

    # Save raw data
    _save_json(bank_data, "bank_transactions.json")
    _save_json(credit_card_data, "credit_card_transactions.json")

    return bank_data, credit_card_data


async def _run_orchestrator(
    username: str,
    start_date: str,
    end_date: str,
    user_query: str
):
    """Main orchestrator agent logic.

    TODO: Implement the orchestrator pattern:
    1. Fetch data from MCP servers (use tools)
    2. Perform initial analysis (detect subscriptions, anomalies)
    3. Decide which sub-agents to invoke based on query
    4. Define sub-agents using AgentDefinition
    5. Invoke sub-agents (can be parallel)
    6. Read and synthesize sub-agent results
    7. Generate final report

    Args:
        username: Username for the account
        start_date: Start date for analysis
        end_date: End date for analysis
        user_query: User's financial question/request
    """
    logger.info(f"Starting financial optimization orchestrator")
    logger.info(f"User query: {user_query}")

    _ensure_directories()

    # Step 1: Fetch financial data from MCP servers
    bank_data, credit_card_data = await _fetch_financial_data(
        username,
        start_date,
        end_date
    )

    # Step 2: Initial analysis
    logger.info("Performing initial analysis...")

    bank_transactions = bank_data.get("transactions", [])
    credit_card_transactions = credit_card_data.get("transactions", [])

    subscriptions = _detect_subscriptions(
        bank_transactions,
        credit_card_transactions
    )

    logger.info(f"Detected {len(subscriptions)} subscriptions")

    # Step 3: Define sub-agents
    # TODO: Define sub-agents using AgentDefinition
    # Example:
    # research_agent = AgentDefinition(
    #     description="Research cheaper alternatives for subscriptions and services",
    #     prompt="""You are a research specialist focused on finding cost savings.
    #     Your job is to research alternatives for subscriptions and services,
    #     compare features, pricing, and provide detailed recommendations.
    #     Write your findings to data/agent_outputs/research_results.json""",
    #     tools=["web_search", "write"],
    #     model="haiku"  # Fast and cheap for research
    # )

    research_agent = AgentDefinition(
        description="Research cheaper alternatives for subscriptions and services",
        prompt=_load_prompt("research_agent_prompt.txt"),
        tools=["write"],
        model="haiku"
    )

    negotiation_agent = AgentDefinition(
        description="Create negotiation strategies and scripts for bills and services",
        prompt=_load_prompt("negotiation_agent_prompt.txt"),
        tools=["write"],
        model="haiku"
    )

    tax_agent = AgentDefinition(
        description="Identify tax-deductible expenses and optimization opportunities",
        prompt=_load_prompt("tax_agent_prompt.txt"),
        tools=["write"],
        model="haiku"
    )

    agents = {
        "research_agent": research_agent,
        "negotiation_agent": negotiation_agent,
        "tax_agent": tax_agent,
    }

    # Step 4: Configure orchestrator agent with sub-agents
    # TODO: Create ClaudeAgentOptions with agents and MCP servers
    # options = ClaudeAgentOptions(
    #     model="sonnet",
    #     system_prompt="""You are a financial optimization coordinator.
    #     You have access to bank and credit card data.
    #     Analyze spending, delegate tasks to specialized agents, and synthesize
    #     their findings into actionable recommendations.""",
    #     agents=agents,
    #     # Add MCP server configurations here
    # )

    mcp_servers = {
        "Bank Account Server": {
            "type": "http",
            "url": "http://127.0.0.1:5001/mcp"
        },
        "Credit Card Server": {
            "type": "http",
            "url": "http://127.0.0.1:5002/mcp"
        }
    }

    working_dir = Path(__file__).parent.parent  # personal-financial-analyst/

    options = ClaudeAgentOptions(
        model="sonnet",
        system_prompt=_load_prompt("orchestrator_system_prompt.txt"),
        mcp_servers=mcp_servers,
        agents=agents,
        can_use_tool=_auto_approve_all,
        cwd=str(working_dir)
    )

    # Step 5: Run orchestrator with Claude Agent SDK
    # TODO: Use ClaudeSDKClient to run the orchestration
    # Example:
    # async with ClaudeSDKClient(options=options) as client:
    #     prompt = f"""Analyze my financial data and {user_query}
    #
    #     I have:
    #     - {len(bank_transactions)} bank transactions
    #     - {len(credit_card_transactions)} credit card transactions
    #     - {len(subscriptions)} identified subscriptions
    #
    #     Please:
    #     1. Identify opportunities for savings
    #     2. Delegate research to the research agent
    #     3. Delegate negotiation strategies to the negotiation agent
    #     4. Delegate tax analysis to the tax agent
    #     5. Read their results and create a final report
    #     """
    #
    #     async for message in client.stream(prompt):
    #         if message.type == "assistant":
    #             print(message.content)

    prompt = f"""Analyze my financial data and {user_query}

I have:
- {len(bank_transactions)} bank transactions
- {len(credit_card_transactions)} credit card transactions
- {len(subscriptions)} identified subscriptions

Please:
1. Identify opportunities for savings
2. Delegate research to the research agent
3. Delegate negotiation strategies to the negotiation agent
4. Delegate tax analysis to the tax agent
5. Read their results and create a final report at data/final_report.md
"""

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text, end='', flush=True)
                print("\n", flush=True)
            elif isinstance(message, ResultMessage):
                logger.info(f"Duration: {message.duration_ms}ms")
                logger.info(f"Cost: ${message.total_cost_usd:.4f}")
                break

    # Step 6: Generate final report
    logger.info("Orchestration complete. Check data/final_report.md for results.")


def _parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Financial Optimization Orchestrator Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
    # Basic analysis
    uv run python financial_orchestrator.py \\
        --username john_doe \\
        --start-date 2026-01-01 \\
        --end-date 2026-01-31 \\
        --query "How can I save $500 per month?"

    # Subscription analysis
    uv run python financial_orchestrator.py \\
        --username jane_smith \\
        --start-date 2026-01-01 \\
        --end-date 2026-01-31 \\
        --query "Analyze my subscriptions and find better deals"
"""
    )

    parser.add_argument(
        "--username",
        type=str,
        required=True,
        help="Username for account (john_doe or jane_smith)"
    )

    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="Start date in YYYY-MM-DD format"
    )

    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="End date in YYYY-MM-DD format"
    )

    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="User's financial question or request"
    )

    return parser.parse_args()


async def main():
    """Main entry point."""
    args = _parse_args()

    await _run_orchestrator(
        username=args.username,
        start_date=args.start_date,
        end_date=args.end_date,
        user_query=args.query
    )


if __name__ == "__main__":
    asyncio.run(main())
