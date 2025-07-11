#database/master_contract_db.py

import os
import pandas as pd
import numpy as np
import httpx
from typing import List, Tuple, Optional, Dict, Any
from utils.httpx_client import get_httpx_client
import requests
import gzip
import shutil
import http.client
import json
import pandas as pd
import gzip
import io


from sqlalchemy import create_engine, Column, Integer, String, Float , Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from database.auth_db import get_auth_token
from extensions import socketio  # Import SocketIO
from utils.logging import get_logger

logger = get_logger(__name__)



# Define the headers as provided
headers = [
    "Fytoken", "Symbol Details", "Exchange Instrument type", "Minimum lot size",
    "Tick size", "ISIN", "Trading Session", "Last update date", "Expiry date",
    "Symbol ticker", "Exchange", "Segment", "Scrip code", "Underlying symbol",
    "Underlying scrip code", "Strike price", "Option type", "Underlying FyToken",
    "Reserved column1", "Reserved column2", "Reserved column3"
]

# Data types for each header
data_types = {
    "Fytoken": str,
    "Symbol Details": str,
    "Exchange Instrument type": int,
    "Minimum lot size": int,
    "Tick size": float,
    "ISIN": str,
    "Trading Session": str,
    "Last update date": str,
    "Expiry date": str,
    "Symbol ticker": str,
    "Exchange": int,
    "Segment": int,
    "Scrip code": int,
    "Underlying symbol": str,
    "Underlying scrip code": pd.Int64Dtype(),
    "Strike price": float,
    "Option type": str,
    "Underlying FyToken": str,
    "Reserved column1": str,  
    "Reserved column2": str, 
    "Reserved column3": str, 
}

DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your database path

engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class SymToken(Base):
    __tablename__ = 'symtoken'
    id = Column(Integer, Sequence('symtoken_id_seq'), primary_key=True)
    symbol = Column(String, nullable=False, index=True)  # Single column index
    brsymbol = Column(String, nullable=False, index=True)  # Single column index
    name = Column(String)
    exchange = Column(String, index=True)  # Include this column in a composite index
    brexchange = Column(String, index=True)  
    token = Column(String, index=True)  # Indexed for performance
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)

    # Define a composite index on symbol and exchange columns
    __table_args__ = (Index('idx_symbol_exchange', 'symbol', 'exchange'),)

def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)

def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()

def copy_from_dataframe(df):
    logger.info("Performing Bulk Insert")
    # Convert DataFrame to a list of dictionaries
    data_dict = df.to_dict(orient='records')

    # Retrieve existing tokens to filter them out from the insert
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}

    # Filter out data_dict entries with tokens that already exist
    filtered_data_dict = [row for row in data_dict if row['token'] not in existing_tokens]

    # Insert in bulk the filtered records
    try:
        if filtered_data_dict:  # Proceed only if there's anything to insert
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Bulk insert completed successfully with {len(filtered_data_dict)} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.exception(f"Error during bulk insert: {e}")
        db_session.rollback()




def download_csv_fyers_data(output_path: str) -> Tuple[bool, List[str], Optional[str]]:
    """
    Download Fyers master contract CSV files using a shared HTTPX client with connection pooling.
    
    Args:
        output_path (str): Directory path where the CSV files will be saved
        
    Returns:
        Tuple[bool, List[str], Optional[str]]: 
            - bool: True if all downloads were successful, False otherwise
            - List[str]: List of paths to downloaded files
            - Optional[str]: Error message if any error occurred, None otherwise
    """
    from utils.httpx_client import get_httpx_client
    logger.info("Downloading Master Contract CSV Files")
    
    # URLs of the CSV files to be downloaded
    csv_urls = {
        "NSE_CD": "https://public.fyers.in/sym_details/NSE_CD.csv",
        "NSE_FO": "https://public.fyers.in/sym_details/NSE_FO.csv",
        "NSE_CM": "https://public.fyers.in/sym_details/NSE_CM.csv",
        "BSE_CM": "https://public.fyers.in/sym_details/BSE_CM.csv",
        "BSE_FO": "https://public.fyers.in/sym_details/BSE_FO.csv",
        "MCX_COM": "https://public.fyers.in/sym_details/MCX_COM.csv"
    }
    
    downloaded_files = []
    errors = []
    
    # Get the shared HTTPX client with connection pooling
    client = get_httpx_client()
    
    try:
        for key, url in csv_urls.items():
            try:
                response = client.get(url, timeout=30.0)
                response.raise_for_status()  # Raises an exception for 4XX/5XX responses
                
                file_path = os.path.join(output_path, f"{key}.csv")
                with open(file_path, 'wb') as file:
                    file.write(response.content)
                downloaded_files.append(file_path)
                logger.info(f"Successfully downloaded {key} to {file_path}")
                
            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP error occurred while downloading {key} from {url}: {e.response.status_code} {e.response.reason_phrase}"
                logger.error(error_msg)
                errors.append(error_msg)
            except httpx.RequestError as e:
                error_msg = f"Request error occurred while downloading {key} from {url}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
            except Exception as e:
                error_msg = f"Unexpected error downloading {key}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
    finally:
        # Don't close the client as it's shared
        pass
    
    # Determine success/failure based on whether we got all files
    success = len(downloaded_files) == len(csv_urls)
    error_msg = "; ".join(errors) if errors else None
    
    return success, downloaded_files, error_msg
    
def reformat_symbol_detail(s):
    parts = s.split()  # Split the string into parts
    # Reorder and format the parts to match the desired output
    # Assuming the format is consistent and always "Name DD Mon YY FUT"
    return f"{parts[0]}{parts[3]}{parts[2].upper()}{parts[1]}{parts[4]}"

def process_fyers_nse_csv(path):
    """
    Processes the Fyers CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Fyers NSE CSV Data")
    file_path = f'{path}/NSE_CM.csv'

    df = pd.read_csv(file_path, names=headers, dtype=data_types)


    # Assigning headers to the DataFrame
    df.columns = headers

    df['token'] = df['Fytoken']
    df['name'] = df['Symbol Details']
    df['expiry'] = df['Expiry date']
    df['strike'] = df['Strike price']
    df['lotsize'] = df['Minimum lot size']
    df['tick_size'] = df['Tick size']
    df['brsymbol'] = df['Symbol ticker']


    # Filtering the DataFrame based on 'Exchange Instrument type' and assigning values to 'exchange'
    df.loc[df['Exchange Instrument type'].isin([0, 9]), 'exchange'] = 'NSE'
    df.loc[df['Exchange Instrument type'].isin([0, 9]), 'instrumenttype'] = 'EQ'
    df.loc[df['Exchange Instrument type'] == 10, 'exchange'] = 'NSE_INDEX'
    df.loc[df['Exchange Instrument type'] == 10, 'instrumenttype'] = 'INDEX'

    # Keeping only rows where 'exchange' column has been filled ('NSE' or 'NSE_INDEX')
    df_filtered = df[df['Exchange Instrument type'].isin([0,9, 10])].copy()

    df_filtered.loc[:, 'symbol'] = df_filtered['Underlying symbol']
    df_filtered['brexchange'] = 'NSE'
    
    # List of columns to remove
    columns_to_remove = [
        "Fytoken", "Symbol Details", "Exchange Instrument type", "Minimum lot size",
        "Tick size", "ISIN", "Trading Session", "Last update date", "Expiry date",
        "Symbol ticker", "Exchange", "Segment", "Scrip code", "Underlying symbol",
        "Underlying scrip code", "Strike price", "Option type", "Underlying FyToken",
        "Reserved column1", "Reserved column2", "Reserved column3"
    ]

    # Removing the specified columns
    token_df = df_filtered.drop(columns=columns_to_remove)


    
    return token_df


def process_fyers_bse_csv(path):
    """
    Processes the Fyers CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Fyers BSE CSV Data")
    file_path = f'{path}/BSE_CM.csv'

    df = pd.read_csv(file_path, names=headers, dtype=data_types)

    # Assigning headers to the DataFrame
    df.columns = headers

    df['token'] = df['Fytoken']
    df['name'] = df['Symbol Details']
    df['expiry'] = df['Expiry date']
    df['strike'] = df['Strike price']
    df['lotsize'] = df['Minimum lot size']
    df['tick_size'] = df['Tick size']
    df['brsymbol'] = df['Symbol ticker']


    # Filtering the DataFrame based on 'Exchange Instrument type' and assigning values to 'exchange'
    df.loc[df['Exchange Instrument type'].isin([0, 4,50]), 'exchange'] = 'BSE'
    df.loc[df['Exchange Instrument type'].isin([0, 4,50]), 'instrumenttype'] = 'EQ'
    df.loc[df['Exchange Instrument type'] == 10, 'exchange'] = 'BSE_INDEX'
    df.loc[df['Exchange Instrument type'] == 10, 'instrumenttype'] = 'INDEX'

    # Keeping only rows where 'exchange' column has been filled ('BSE' or 'BSE_INDEX')
    df_filtered = df[df['Exchange Instrument type'].isin([0, 4, 10, 50])].copy()

    df_filtered.loc[:, 'symbol'] = df_filtered['Underlying symbol']

    df_filtered['brexchange'] = 'BSE'

    # List of columns to remove
    columns_to_remove = [
        "Fytoken", "Symbol Details", "Exchange Instrument type", "Minimum lot size",
        "Tick size", "ISIN", "Trading Session", "Last update date", "Expiry date",
        "Symbol ticker", "Exchange", "Segment", "Scrip code", "Underlying symbol",
        "Underlying scrip code", "Strike price", "Option type", "Underlying FyToken",
        "Reserved column1", "Reserved column2", "Reserved column3"
    ]

    # Removing the specified columns
    token_df = df_filtered.drop(columns=columns_to_remove)
    
    return token_df

def process_fyers_nfo_csv(path):
    """
    Processes the Fyers CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Fyers NFO CSV Data")
    file_path = f'{path}/NSE_FO.csv'

    df = pd.read_csv(file_path, names=headers, dtype=data_types)

    df['token'] = df['Fytoken']
    df['name'] = df['Symbol Details']

    # Convert 'Expiry date' from Unix timestamp to datetime
    df['expiry'] = pd.to_datetime(df['Expiry date'], unit='s')

    # Format the datetime object to the desired format '15-APR-24'
    df['expiry'] = df['expiry'].dt.strftime('%d-%b-%y').str.upper()

    df['strike'] = df['Strike price']
    df['lotsize'] = df['Minimum lot size']
    df['tick_size'] = df['Tick size']
    df['brsymbol'] = df['Symbol ticker']
    df['brexchange'] = 'NFO'
    df['exchange'] = 'NFO'
    df['instrumenttype'] = df['Option type'].str.replace('XX','FUT')


    # Apply the function to rows where 'Option type' is 'XX'
    df.loc[df['Option type'] == 'XX', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)
    df.loc[df['Option type'] == 'CE', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)+'CE'
    df.loc[df['Option type'] == 'PE', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)+'PE'

    # List of columns to remove
    columns_to_remove = [
        "Fytoken", "Symbol Details", "Exchange Instrument type", "Minimum lot size",
        "Tick size", "ISIN", "Trading Session", "Last update date", "Expiry date",
        "Symbol ticker", "Exchange", "Segment", "Scrip code", "Underlying symbol",
        "Underlying scrip code", "Strike price", "Option type", "Underlying FyToken",
        "Reserved column1", "Reserved column2", "Reserved column3"
    ]

    # Removing the specified columns
    token_df = df.drop(columns=columns_to_remove)
    
    return token_df


def process_fyers_cds_csv(path):
    """
    Processes the Fyers CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Fyers CDS CSV Data")
    file_path = f'{path}/NSE_CD.csv'

    df = pd.read_csv(file_path, names=headers, dtype=data_types)

    df['token'] = df['Fytoken']
    df['name'] = df['Symbol Details']

    # Convert 'Expiry date' from Unix timestamp to datetime
    df['expiry'] = pd.to_datetime(df['Expiry date'], unit='s')

    # Format the datetime object to the desired format '15-APR-24'
    df['expiry'] = df['expiry'].dt.strftime('%d-%b-%y').str.upper()

    df['strike'] = df['Strike price']
    df['lotsize'] = df['Minimum lot size']
    df['tick_size'] = df['Tick size']
    df['brsymbol'] = df['Symbol ticker']
    df['brexchange'] = 'CDS'
    df['exchange'] = 'CDS'
    df['instrumenttype'] = df['Option type'].str.replace('XX','FUT')


    # Apply the function to rows where 'Option type' is 'XX'
    df.loc[df['Option type'] == 'XX', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)
    df.loc[df['Option type'] == 'CE', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)+'CE'
    df.loc[df['Option type'] == 'PE', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)+'PE'

    # List of columns to remove
    columns_to_remove = [
        "Fytoken", "Symbol Details", "Exchange Instrument type", "Minimum lot size",
        "Tick size", "ISIN", "Trading Session", "Last update date", "Expiry date",
        "Symbol ticker", "Exchange", "Segment", "Scrip code", "Underlying symbol",
        "Underlying scrip code", "Strike price", "Option type", "Underlying FyToken",
        "Reserved column1", "Reserved column2", "Reserved column3"
    ]

    # Removing the specified columns
    token_df = df.drop(columns=columns_to_remove)
    
    return token_df


def process_fyers_bfo_csv(path):
    """
    Processes the Fyers CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Fyers BFO CSV Data")
    file_path = f'{path}/BSE_FO.csv'

    df = pd.read_csv(file_path, names=headers, dtype=data_types)

    df['token'] = df['Fytoken']
    df['name'] = df['Symbol Details']

    # Convert 'Expiry date' from Unix timestamp to datetime
    df['expiry'] = pd.to_datetime(df['Expiry date'], unit='s')

    # Format the datetime object to the desired format '15-APR-24'
    df['expiry'] = df['expiry'].dt.strftime('%d-%b-%y').str.upper()

    df['strike'] = df['Strike price']
    df['lotsize'] = df['Minimum lot size']
    df['tick_size'] = df['Tick size']
    df['brsymbol'] = df['Symbol ticker']
    df['brexchange'] = 'BFO'
    df['exchange'] = 'BFO'
    df['instrumenttype'] = df['Option type'].fillna('FUT').str.replace('XX', 'FUT')


    # Apply the function to rows where 'Option type' is 'XX'
    df.loc[(df['Option type'] == 'XX') | df['Option type'].isna(), 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)
    df.loc[df['Option type'] == 'CE', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)+'CE'
    df.loc[df['Option type'] == 'PE', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)+'PE'

    # List of columns to remove
    columns_to_remove = [
        "Fytoken", "Symbol Details", "Exchange Instrument type", "Minimum lot size",
        "Tick size", "ISIN", "Trading Session", "Last update date", "Expiry date",
        "Symbol ticker", "Exchange", "Segment", "Scrip code", "Underlying symbol",
        "Underlying scrip code", "Strike price", "Option type", "Underlying FyToken",
        "Reserved column1", "Reserved column2", "Reserved column3"
    ]

    # Removing the specified columns
    token_df = df.drop(columns=columns_to_remove)

    return token_df

def process_fyers_mcx_csv(path):
    """
    Processes the Fyers CSV file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Fyers MCX CSV Data")
    file_path = f'{path}/MCX_COM.csv'

    df = pd.read_csv(file_path, names=headers, dtype=data_types)

    df['token'] = df['Fytoken']
    df['name'] = df['Symbol Details']

    # Convert 'Expiry date' from Unix timestamp to datetime
    df['expiry'] = pd.to_datetime(df['Expiry date'], unit='s')

    # Format the datetime object to the desired format '15-APR-24'
    df['expiry'] = df['expiry'].dt.strftime('%d-%b-%y').str.upper()

    df['strike'] = df['Strike price']
    df['lotsize'] = df['Minimum lot size']
    df['tick_size'] = df['Tick size']
    df['brsymbol'] = df['Symbol ticker']
    df['brexchange'] = 'MCX'
    df['exchange'] = 'MCX'
    df['instrumenttype'] = df['Option type'].str.replace('XX','FUT')



    # Apply the function to rows where 'Option type' is 'XX'
    df.loc[df['Option type'] == 'XX', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)
    df.loc[df['Option type'] == 'CE', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)+'CE'
    df.loc[df['Option type'] == 'PE', 'symbol'] = df['Symbol Details'].apply(lambda x: reformat_symbol_detail(x) if pd.notnull(x) else x)+'PE'

    # List of columns to remove
    columns_to_remove = [
        "Fytoken", "Symbol Details", "Exchange Instrument type", "Minimum lot size",
        "Tick size", "ISIN", "Trading Session", "Last update date", "Expiry date",
        "Symbol ticker", "Exchange", "Segment", "Scrip code", "Underlying symbol",
        "Underlying scrip code", "Strike price", "Option type", "Underlying FyToken",
        "Reserved column1", "Reserved column2", "Reserved column3"
    ]

    # Removing the specified columns
    token_df = df.drop(columns=columns_to_remove)




    
    return token_df

    

def delete_fyers_temp_data(output_path):
    # Check each file in the directory
    for filename in os.listdir(output_path):
        # Construct the full file path
        file_path = os.path.join(output_path, filename)
        # If the file is a CSV, delete it
        if filename.endswith(".csv") and os.path.isfile(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Deleted {file_path}")
            except OSError as e:
                logger.warning(f"Error deleting file {file_path}: {e}")


def master_contract_download():
    logger.info(f"Downloading Master Contract")
    

    output_path = 'tmp'
    try:
        download_csv_fyers_data(output_path)
        delete_symtoken_table()
        token_df = process_fyers_nse_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_fyers_bse_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_fyers_bfo_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_fyers_nfo_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_fyers_cds_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_fyers_mcx_csv(output_path)
        copy_from_dataframe(token_df)
        delete_fyers_temp_data(output_path)
        #token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)
        
        #token_df = token_df.drop_duplicates(subset='symbol', keep='first')
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    
    except Exception as e:
        logger.exception(f"{e}")
        return socketio.emit('master_contract_download', {'status': 'error', 'message': f"{e}"})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
