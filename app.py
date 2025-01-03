import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# -------------------------------------------------------------------
# 1. Configuration
# -------------------------------------------------------------------
# Replace with your actual Helius API key, or read from environment vars.
HELIUS_API_KEY = "2d8b5f7e-5bba-48f5-bd33-d2cafa8126ff"
HELIUS_BASE_URL = "https://api.helius.xyz/v0/addresses"

# -------------------------------------------------------------------
# 2. Fetch Transactions from Helius
# -------------------------------------------------------------------
def fetch_solana_transactions(wallet_address, limit=100):
    """
    Fetches transaction data from Helius for the provided Solana wallet address.
    'limit' controls how many transactions we fetch in one call (max 1,000).
    You can implement pagination if you have many transactions.
    """
    url = f"{HELIUS_BASE_URL}/{wallet_address}/transactions?api-key={HELIUS_API_KEY}&limit={limit}"
    response = requests.get(url)
    response.raise_for_status()  # will raise an HTTPError if the request fails
    return response.json()  # This returns a list of transaction objects

# -------------------------------------------------------------------
# 3. Parse & Structure the Transactions
# -------------------------------------------------------------------
def parse_transactions(raw_txs, wallet_address):
    """
    Convert the raw Helius transaction data into a structured list of dicts.
    We'll attempt to identify "buy" vs. "sell" or simple transfers.
    
    NOTE: This is a simplified approach. Real DEX trades might need extra logic
    to detect if the user actually bought or sold a token (e.g., checking program IDs).
    """
    parsed = []

    for tx in raw_txs:
        # Each "tx" is a dictionary containing "timestamp", "tokenTransfers", etc.
        timestamp = tx.get("timestamp", 0)
        date_str = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S (UTC)')

        token_transfers = tx.get("tokenTransfers", [])
        # If there are no tokenTransfers, it might be an SOL transfer or something else.
        # For demonstration, let's process tokenTransfers first:
        if token_transfers:
            for transfer in token_transfers:
                symbol = "UNKNOWN"
                token_mint = transfer.get("tokenAddress", "")
                # In a real scenario, you'd map the token mint to a known symbol or call
                # Helius' token metadata endpoint. For now, let's assume SOL or generic "SPL".

                # Distinguish if this is an "incoming" or "outgoing" for the wallet
                to_addr = transfer.get("toUserAccount", "")
                from_addr = transfer.get("fromUserAccount", "")
                amount_raw = transfer.get("amount", 0)
                decimals = transfer.get("decimals", 0)
                amount = amount_raw / (10 ** decimals) if decimals else amount_raw

                side = ""
                if to_addr.lower() == wallet_address.lower():
                    side = "buy"
                elif from_addr.lower() == wallet_address.lower():
                    side = "sell"
                else:
                    side = "transfer"

                # Attempt to set a symbol if it's a known SPL mint or native SOL
                if token_mint == "So11111111111111111111111111111111111111112":
                    symbol = "SOL"
                else:
                    # Placeholder. In a real app, you'd query metadata to get symbol
                    symbol = token_mint[:4]  # e.g., first 4 chars

                parsed.append({
                    "date": date_str,
                    "symbol": symbol,
                    "token_mint": token_mint,
                    "amount": amount,
                    "side": side,
                    # We'll fill in price_at_tx later if we have a price feed
                    "price_at_tx": 0.0
                })

        # If there are "nativeTransfers" (SOL moves) but no tokenTransfers:
        # Helius merges them, but sometimes you'll see "nativeTransfers" in the raw JSON
        native_transfers = tx.get("nativeTransfers", [])
        if native_transfers:
            for ntransfer in native_transfers:
                # Distinguish if it's inbound or outbound for the wallet
                to_addr = ntransfer.get("toUserAccount", "")
                from_addr = ntransfer.get("fromUserAccount", "")
                lamports = ntransfer.get("amount", 0)  # in lamports
                amount_sol = lamports / 1e9

                side = ""
                if to_addr.lower() == wallet_address.lower():
                    side = "buy"
                elif from_addr.lower() == wallet_address.lower():
                    side = "sell"
                else:
                    side = "transfer"

                parsed.append({
                    "date": date_str,
                    "symbol": "SOL",
                    "token_mint": "NativeSOL",
                    "amount": amount_sol,
                    "side": side,
                    "price_at_tx": 0.0
                })

    return parsed

# -------------------------------------------------------------------
# 4. Calculate Profit and Loss (PnL)
# -------------------------------------------------------------------
def calculate_pnl(transactions):
    """
    This function attempts a naive buy/sell matching approach for each token.
    In reality, you'd need a more detailed approach if you have partial trades or multiple tokens.
    We'll do a basic LIFO approach (last in, first out) per token symbol.
    """
    df = pd.DataFrame(transactions)
    
    # Convert 'date' back to a true datetime for sorting and manipulations
    df['date'] = pd.to_datetime(df['date'].str.replace(' (UTC)', '', regex=False), format='%Y-%m-%d %H:%M:%S')

    # We'll group by symbol to track buy/sell pairs per token
    results = []
    for symbol, group in df.groupby('symbol', sort=False):
        group = group.sort_values('date')
        
        # We'll track a stack of buys:
        buy_stack = []  # list of (amount, price_at_tx)
        pnl_list = []
        for idx, row in group.iterrows():
            side = row['side']
            amount = row['amount']
            price_at_tx = row['price_at_tx']  # Currently 0.0 unless you feed real prices

            # For demonstration, let's assume we consider the price at the time of the tx = 20.0 USD for SOL, etc.
            # In real use, you'd fetch historical price from CoinGecko or Helius if available.
            # Let's do a mock price to show how PnL might be computed:
            mock_price = 20.0 if row['symbol'] == "SOL" else 1.0  # TOTALLY FAKE
            # Overwrite price_at_tx with mock
            price_at_tx = mock_price

            if side == "buy":
                # push onto buy stack
                buy_stack.append([amount, price_at_tx])
                pnl_list.append(0.0)
            elif side == "sell":
                # we need to pop from buy stack
                remaining_sell = amount
                total_sell_pnl = 0.0

                while remaining_sell > 0 and buy_stack:
                    last_buy = buy_stack.pop()
                    buy_amt, buy_price = last_buy
                    if buy_amt <= remaining_sell:
                        # Sell the entire chunk
                        total_sell_pnl += (price_at_tx - buy_price) * buy_amt
                        remaining_sell -= buy_amt
                    else:
                        # partial sell from this chunk
                        total_sell_pnl += (price_at_tx - buy_price) * remaining_sell
                        leftover = buy_amt - remaining_sell
                        buy_stack.append([leftover, buy_price])  # put remainder back
                        remaining_sell = 0

                pnl_list.append(total_sell_pnl)
            else:
                # It's a transfer, no PnL
                pnl_list.append(0.0)

        # Combine PnL into group
        group['pnl'] = pnl_list
        results.append(group)

    if results:
        final_df = pd.concat(results).sort_values('date', ascending=False)
    else:
        final_df = df
        final_df['pnl'] = 0.0

    return final_df

# -------------------------------------------------------------------
# 5. Streamlit App to Display & Filter
# -------------------------------------------------------------------
def main():
    st.title("Solana Wallet Transactions & PnL Viewer (via Helius)")
    st.write("Enter your Solana wallet address (Photon SOL, Phantom, etc.) to see transactions.")

    wallet_address = st.text_input("Wallet Address:")
    limit = st.number_input("Number of transactions to fetch (limit)", min_value=10, max_value=1000, value=100)
    
    if st.button("Fetch Data"):
        try:
            raw_data = fetch_solana_transactions(wallet_address, limit=limit)
            parsed_data = parse_transactions(raw_data, wallet_address)
            if not parsed_data:
                st.warning("No transactions found or unable to parse. Check your wallet address or the limit.")
                return
            
            df_with_pnl = calculate_pnl(parsed_data)

            # Format the date column to a nicer string
            df_with_pnl['date'] = df_with_pnl['date'].dt.strftime('%Y-%m-%d %H:%M:%S')

            # Reorder columns for readability
            display_cols = ["date", "symbol", "amount", "side", "price_at_tx", "pnl"]
            df_final = df_with_pnl[display_cols].copy()
            df_final.rename(columns={
                "date": "Date",
                "symbol": "Ticker",
                "amount": "Amount",
                "side": "Side",
                "price_at_tx": "Price (Mock)",
                "pnl": "PnL (Mock)"
            }, inplace=True)

            st.write("### All Transactions (with Mock Price & PnL)")
            st.dataframe(df_final, use_container_width=True)

            # ---------------------------
            # Filter UI
            # ---------------------------
            st.write("### Filter Options")

            # Filter by Ticker
            tickers = df_final['Ticker'].unique().tolist()
            selected_ticker = st.selectbox("Filter by Ticker", ["All"] + tickers)
            if selected_ticker != "All":
                df_final = df_final[df_final['Ticker'] == selected_ticker]

            # Filter by Side
            sides = df_final['Side'].unique().tolist()
            selected_side = st.selectbox("Filter by Side", ["All"] + sides)
            if selected_side != "All":
                df_final = df_final[df_final['Side'] == selected_side]

            # Display filtered results
            st.write("### Filtered Results")
            st.dataframe(df_final, use_container_width=True)

        except Exception as e:
            st.error(f"Error fetching or processing data: {e}")

if __name__ == "__main__":
    main()
