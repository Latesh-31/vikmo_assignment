"""
VIKMO DealerDesk — Groq LLM Assistant with Tool Calling
Implements the AI Assistant per API Contract §9 using Groq's tool calling API.
"""

import json
import os
from typing import Dict, List, Any, Optional
from groq import Groq
from django.conf import settings

from .assistant_context import get_company_context
from products.models import Product
from orders.services import create_draft_order


class GroqAssistant:
    """Groq-based AI Assistant with tool calling for VIKMO DealerDesk."""

    # Tool definitions for Groq function calling
    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "search_parts",
                "description": "Search the motorcycle parts catalogue. Use this when the user asks about parts, products, or wants to find items.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (part name, SKU, keyword)"
                        },
                        "vehicle": {
                            "type": "string",
                            "description": "Vehicle fitment filter (e.g., 'Pulsar 150', 'Apache')"
                        },
                        "category": {
                            "type": "string",
                            "description": "Product category filter (e.g., 'Brakes', 'Filters', 'Drivetrain')"
                        },
                        "brand": {
                            "type": "string",
                            "description": "Brand filter (e.g., 'Endurance', 'Bosch')"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_stock",
                "description": "Check real-time stock level for a specific SKU. Use this when the user asks about stock, availability, or quantity for a specific part number.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sku": {
                            "type": "string",
                            "description": "Product SKU (format: XXX-XXXX, e.g., BRK-1044)"
                        }
                    },
                    "required": ["sku"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_draft_order",
                "description": "Create a draft order for a dealer. Use this when the user explicitly wants to place an order or create a draft order. Requires dealer_id from session.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dealer_id": {
                            "type": "integer",
                            "description": "Dealer ID (provided in session context)"
                        },
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "sku": {"type": "string"},
                                    "quantity": {"type": "integer", "minimum": 1}
                                },
                                "required": ["sku", "quantity"]
                            }
                        }
                    },
                    "required": ["dealer_id", "items"]
                }
            }
        }
    ]

    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY") or getattr(settings, "GROQ_API_KEY", None)
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment or settings")
        self.client = Groq(api_key=api_key)
        self.model = "qwen/qwen3.8-27b"  # Groq model that supports tool calling
        self.context = get_company_context()
        self._session_histories: Dict[str, List[Dict]] = {}

    def _build_system_prompt(self, dealer_id: Optional[int] = None) -> str:
        """Build the system prompt with company context and tool instructions."""
        stats = self.context.get_stats_summary()
        info = self.context._company_info

        dealer_info = ""
        if dealer_id:
            dealer = self.context.get_dealer_by_id(dealer_id)
            if dealer:
                dealer_info = f"\nCURRENT DEALER: {dealer['name']} [{dealer['dealer_code']}] (ID: {dealer_id})"

        return f"""You are the AI Assistant for {info['name']} — {info['tagline']}.

COMPANY CONTEXT:
{info['description']}{dealer_info}

KEY CAPABILITIES:
{chr(10).join(f"- {c}" for c in info['capabilities'])}

CURRENT INVENTORY SNAPSHOT:
- Total Products: {stats['total_products']}
- Total Dealers: {stats['total_dealers']}
- Low Stock Items (<15): {stats['low_stock_count']}
- Out of Stock: {stats['out_of_stock_count']}
- Inventory Value: ₹{stats['total_inventory_value']:,.2f}
- Categories: {', '.join(stats['categories'])}
- Top Brands: {', '.join(stats['brands'])}

POLICIES:
- Payment: {info['policies']['payment_terms']}
- Minimum Order: {info['policies']['minimum_order']}
- Shipping: {info['policies']['shipping']}
- Returns: {info['policies']['returns']}
- GST: {info['policies']['gst']}

AVAILABLE TOOLS:
1. search_parts(query, vehicle?, category?, brand?) — Search parts catalogue
2. check_stock(sku) — Check real-time stock for a SKU
3. create_draft_order(dealer_id, items) — Create a draft order for a dealer

TOOL USAGE RULES:
- ALWAYS use tools for parts searches, stock checks, and order creation — never guess or use general knowledge
- For parts queries: use search_parts with appropriate filters
- For stock queries with a specific SKU: use check_stock
- For order creation: use create_draft_order with dealer_id from context (already provided)
- If the user asks about company policies, capabilities, or general info, answer directly from context
- Be concise and helpful
- Use ₹ for currency with 2 decimals
- Reference SKUs when mentioning parts
- If creating orders, confirm details before proceeding
- For off-topic requests, politely decline and redirect to what you can help with

RESPONSE FORMAT:
- Provide a natural language reply to the user
- The system will automatically track tool calls and cited SKUs
"""

    def _get_or_create_history(self, session_id: str, dealer_id: Optional[int] = None) -> List[Dict]:
        """Get or create conversation history for a session."""
        if session_id not in self._session_histories:
            self._session_histories[session_id] = [
                {"role": "system", "content": self._build_system_prompt(dealer_id)}
            ]
        return self._session_histories[session_id]

    def _execute_tool(self, tool_name: str, arguments: Dict, dealer_id: int) -> Dict[str, Any]:
        """Execute a tool call and return the result."""
        if tool_name == "search_parts":
            query = arguments.get("query", "")
            vehicle = arguments.get("vehicle", "")
            category = arguments.get("category", "")
            brand = arguments.get("brand", "")

            matches = self.context.search_catalogue(
                query=query,
                category=category,
                vehicle=vehicle,
                brand=brand,
                limit=8,
            )

            return {
                "results": matches,
                "count": len(matches),
                "formatted": [self.context.format_product_for_reply(p) for p in matches]
            }

        elif tool_name == "check_stock":
            sku = arguments.get("sku", "").upper().strip()
            product = Product.objects.filter(sku=sku).first()
            if product:
                return {
                    "sku": product.sku,
                    "name": product.name,
                    "stock": product.stock,
                    "price": str(product.price),
                    "status": "Out of Stock" if product.stock == 0 else ("Low Stock" if product.stock < 15 else "In Stock")
                }
            else:
                return {"error": f"SKU {sku} not found"}

        elif tool_name == "create_draft_order":
            items = arguments.get("items", [])
            try:
                order = create_draft_order(dealer_id=dealer_id, items_data=items)
                return {
                    "order_number": order.order_number,
                    "status": "DRAFT",
                    "grand_total": str(order.grand_total),
                    "items": [
                        {"sku": item.sku, "name": item.name, "quantity": item.quantity, "unit_price": str(item.unit_price)}
                        for item in order.items.all()
                    ]
                }
            except Exception as e:
                return {"error": str(e)}

        return {"error": f"Unknown tool: {tool_name}"}

    def chat(self, session_id: str, dealer_id: int, message: str) -> Dict[str, Any]:
        """Process a chat message and return the response with tool calls."""
        history = self._get_or_create_history(session_id, dealer_id)

        # Add user message to history
        history.append({"role": "user", "content": message})

        # Keep history manageable (last 20 messages + system)
        if len(history) > 21:
            history = [history[0]] + history[-20:]

        # Call Groq with tools
        response = self.client.chat.completions.create(
            model=self.model,
            messages=history,
            tools=self.TOOLS,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=1000,
        )

        message_obj = response.choices[0].message
        tool_calls = []
        cited_skus = set()
        actions = []

        # Handle tool calls
        if message_obj.tool_calls:
            # Add assistant message with tool calls to history
            history.append({
                "role": "assistant",
                "content": message_obj.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    }
                    for tc in message_obj.tool_calls
                ]
            })

            # Execute each tool call
            for tool_call in message_obj.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                tool_calls.append({
                    "name": tool_name,
                    "arguments": arguments
                })

                result = self._execute_tool(tool_name, arguments, dealer_id)

                # Track cited SKUs
                if tool_name == "search_parts" and result.get("results"):
                    for p in result["results"]:
                        cited_skus.add(p["sku"])
                elif tool_name == "check_stock" and result.get("sku"):
                    cited_skus.add(result["sku"])
                elif tool_name == "create_draft_order" and result.get("order_number"):
                    actions.append({"type": "draft_order_created", "order_number": result["order_number"]})
                    for item in result.get("items", []):
                        cited_skus.add(item["sku"])

                # Add tool result to history
                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })

            # Get final response from model after tool execution
            final_response = self.client.chat.completions.create(
                model=self.model,
                messages=history,
                temperature=0.1,
                max_tokens=500,
            )
            reply = final_response.choices[0].message.content or ""
            history.append({"role": "assistant", "content": reply})
        else:
            # No tool calls, just a direct response
            reply = message_obj.content or ""
            history.append({"role": "assistant", "content": reply})

        return {
            "reply": reply,
            "cited_skus": sorted(list(cited_skus)),
            "tool_calls": tool_calls,
            "actions": actions
        }

    def clear_session(self, session_id: str):
        """Clear conversation history for a session."""
        if session_id in self._session_histories:
            del self._session_histories[session_id]


# Global instance (lazy initialization)
_groq_assistant = None


def get_groq_assistant() -> GroqAssistant:
    """Get the global Groq assistant instance (lazy init)."""
    global _groq_assistant
    if _groq_assistant is None:
        _groq_assistant = GroqAssistant()
    return _groq_assistant