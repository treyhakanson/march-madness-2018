from bs4 import BeautifulSoup
import requests
import pandas as pd
from os import path
from dateutil.parser import parse
from datetime import datetime
from constants import SCHOOLS
import utils

PIPELINE = [
    'rosters',
    'schedules',
    'opponent-rosters',
    'boxscores'
]

schedule_failures = set()
roster_failures = set()
boxscore_failures = set()


def format_table(rows):
    return list(map(lambda x: tuple(map(lambda x: x.get_text(), x.children)),
                rows))


def get_roster(school):
    print('Retrieveing ROSTER for %s' % (school.upper()))
    if (path.isfile(utils.roster_file_path(school))):
        return
    r = requests.get(utils.roster_url(school))
    if (r.status_code != 200):
        print('\tFailed to get ROSTER for %s' % (school.upper()))
        roster_failures.add(school)
        return
    soup = BeautifulSoup(r.text, 'html.parser')
    roster = format_table(soup.select('table#roster tbody tr'))
    df = pd.DataFrame.from_records(roster)
    if df.shape[1] == 10: # Some high-level teams have an extra RSCI column
        df = df.drop([8], axis=1)
    df.columns = ['Name', 'Number', 'Year', 'Position', 'Height', 'Weight',
                  'Hometown', 'High School', 'Stats']
    df[['PPG', 'RPG', 'APG']] = df['Stats'].str.split(', ', expand=True)
    df = df[['Name', 'Number', 'Year', 'Position', 'Height', 'Weight',
             'Hometown', 'High School', 'PPG', 'RPG', 'APG']]
    df.to_csv(utils.roster_file_path(school), sep=',', encoding='utf-8')


def get_schedule(school):
    print('Retrieveing SCHEDULE for %s' % (school.upper()))
    if (path.isfile(utils.schedule_file_path(school))):
        return
    r = requests.get(utils.schedule_url(school))
    if (r.status_code != 200):
        print('\tFailed to get SCHEDULE for %s' % (school.upper()))
        schedule_failures.add(school)
        return
    soup = BeautifulSoup(r.text, 'html.parser')
    schedule = format_table(soup.find('table', id='schedule').find('tbody')
                            .find_all('tr', class_=''))
    df = pd.DataFrame.from_records(schedule)
    df.columns = ['Game', 'Date', 'Time', 'Type', 'Home/Away',
                  'Opponent', 'Conference', 'Outcome', 'Team Points',
                  'Opponent Points', 'OT', 'Opponent Wins', 'Opponent Losses',
                  'Streak', 'Arena']
    df.to_csv(utils.schedule_file_path(school), sep=',', encoding='utf-8')


def get_boxscore(school, row):
    dt = parse(row['Date'])
    dt = '%d-%02d-%02d' % (dt.year, dt.month, dt.day)
    tm = '%02d' % (datetime.strptime(row['Time'] + 'm', '%I:%M%p')
                   .time().hour)
    ha = str(row['Home/Away'])
    opponent = utils.clean_opponent_name(row['Opponent'])

    print("Getting BOXSCORE form game between %s and %s"
          % (school.upper(), opponent.upper()))

    if (
        path.isfile(utils.boxscore_file_path(school, dt, tm)) and path
        .isfile(utils.boxscore_file_path(opponent, dt, tm))
    ):
        return

    url_school = opponent if '@' in ha else school
    url = utils.boxscore_url(url_school, dt, tm)
    print("\tRequesting: %s" % (url))
    r = requests.get(url)

    # When `ha` is 'N', the school needed in the url appears to be
    # somewhat random, so if the request fails try the other school
    if r.status_code == 404:
        url_school = school if '@' in ha else opponent
        url = utils.boxscore_url(url_school, dt, tm)
        print('\tURL failed, attempting to use backup: %s' % (url))
        r = requests.get(url)

    if r.status_code == 404:
        print('\tFailed to get boxscore')
        boxscore_failures.add(url)
        return

    soup = BeautifulSoup(r.text, 'html.parser')

    try:
        school_stats = format_table(soup.find('table',
                                    id='box-score-basic-%s' % (school))
                                    .find('tbody')
                                    .find_all('tr', class_=''))
        opponent_stats = format_table(soup.find('table',
                                      id='box-score-basic-%s'
                                      % (opponent)).find('tbody')
                                      .find_all('tr', class_=''))

    except Exception as e:
        # Sometimes the name should not be mapped during cleaning when
        # getting boxscores; attempt to use a "gently" cleaned name
        print('\tBad name. Attempting to recover.')
        try:
            opponent_alt = utils.gentle_clean_opponent_name(row['Opponent'])
            school_stats = format_table(soup.find('table',
                                        id='box-score-basic-%s'
                                        % (school)).find('tbody')
                                        .find_all('tr', class_=''))
            opponent_stats = format_table(soup.find('table',
                                          id='box-score-basic-%s'
                                          % (opponent_alt))
                                          .find('tbody')
                                          .find_all('tr', class_=''))
            print('\tRecovered!')
        except Exception as e:
            boxscore_failures.add(url)
            print('''
                ERROR: there was likely a bad name involved when
                trying to select the tables. Teams involved were: %s
                and %s (later is likely the issue; an alias should be
                added to OPPONENT_MAP)
            ''' % (school, opponent))
            return

    dt1 = pd.DataFrame.from_records(school_stats)
    dt2 = pd.DataFrame.from_records(opponent_stats)

    cols = ['Name', 'MP', 'FG', 'FGA', 'FG%', '2P', '2PA', '2P%', '3P',
            '3PA', '3P%', 'FT', 'FTA', 'FT%', 'ORB', 'DRB', 'TRB',
            'AST', 'STL', 'BLK', 'TOV', 'PF', 'PTS']

    dt1.columns = cols
    dt2.columns = cols

    dt1.to_csv(utils.boxscore_file_path(school, dt, tm), sep=',',
               encoding='utf-8')
    dt2.to_csv(utils.boxscore_file_path(opponent, dt, tm), sep=',',
               encoding='utf-8')


# Get Rosters
if 'rosters' in PIPELINE:
    for school in SCHOOLS:
        get_roster(school)

# Get Schedules
if 'schedules' in PIPELINE:
    for school in SCHOOLS:
        get_schedule(school)

# Get Rosters of Teams in Schedules
if 'opponent-rosters' in PIPELINE:
    for school in SCHOOLS:
        print('Getting rosters for schedule of %s' % (school.upper()))
        df = pd.read_csv(utils.schedule_file_path(school))
        df['Opponent'] = df['Opponent'].apply(utils.clean_opponent_name)
        for opponent in df['Opponent']:
            get_roster(opponent)
        print('\n')

# Get Boxscores
if 'boxscores' in PIPELINE:
    for school in SCHOOLS:
        df = pd.read_csv(utils.schedule_file_path(school))
        for i, row in df.iterrows():
            # Last row is the unplayed tournament game
            if i == len(df) - 1:
                continue
            get_boxscore(school, row)

with open('../roster-failures.log', 'a') as file:
    file.write('\n'.join(roster_failures))

with open('../schedule-failures.log', 'a') as file:
    file.write('\n'.join(schedule_failures))

with open('../boxscore-failures.log', 'a') as file:
    file.write('\n'.join(boxscore_failures))
