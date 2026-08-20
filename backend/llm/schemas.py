CONCERT_SINGER_SCHEMA = """
Table: concert_singer.stadium
Columns: Stadium_ID, Location, Name, Capacity, Highest, Lowest, Average

Table: concert_singer.singer
Columns: Singer_ID, Name, Country, Song_Name, Song_release_year, Age, Is_male

Table: concert_singer.concert
Columns: concert_ID, concert_Name, Theme, Stadium_ID, Year

Table: concert_singer.singer_in_concert
Columns: concert_ID, Singer_ID
"""
