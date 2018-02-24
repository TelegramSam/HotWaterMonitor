from __future__ import print_function
from datetime import datetime, timedelta
from pytz import timezone
import pytz
import isodate
import boto3
import re
import math

# Create CloudWatch client
cloudwatch_client = boto3.client('cloudwatch')


# config values
capacity_gallons = 50
shower_liters_per_minute = 8.4


capacity_liters = capacity_gallons / 0.264172

# --------------- Helpers that build all of the responses ----------------------

def build_speechlet_response(title, output, reprompt_text, should_end_session):
    return {
        'outputSpeech': {
            'type': 'PlainText',
            'text': output
        },
        'card': {
            'type': 'Simple',
            'title': "Hot Water - " + title,
            'content': output
        },
        'reprompt': {
            'outputSpeech': {
                'type': 'PlainText',
                'text': reprompt_text
            }
        },
        'shouldEndSession': should_end_session
    }


def build_response(session_attributes, speechlet_response):
    return {
        'version': '1.0',
        'sessionAttributes': session_attributes,
        'response': speechlet_response
    }


# --------------- Functions that control the skill's behavior ------------------

def get_welcome_response():
    """ If we wanted to initialize the session to have some attributes we could
    add those here
    """

    session_attributes = {}
    card_title = "Welcome"
    speech_output = "Welcome to your Hot Water Heater. "
    # If the user either does not reply to the welcome message or says something
    # that is not understood, they will be prompted again with this text.
    reprompt_text = "You can ask me how much water you've used recently, how much water is left, or how long you can shower. "
    should_end_session = False
    return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, reprompt_text, should_end_session))


def handle_session_end_request():
    card_title = "Session Ended"
    speech_output = "Thank you for talking to your Hot Water Heater. " \
                    "Have a nice day! "
    # Setting this to true ends the session and exits the skill.
    should_end_session = True
    return build_response({}, build_speechlet_response(
        card_title, speech_output, None, should_end_session))

def length_of_shower(intent, session):
    """ Calculate length of shower based on expected flow rate.
    """

    card_title = "Shower Time"
    session_attributes = {}
    should_end_session = session['new']

    usertimezone = timezone('US/Mountain')
    endtime = datetime.now(usertimezone)
    starttime = endtime - timedelta(minutes=2)
    

    #query cloudwatch for liters used.
    response = cloudwatch_client.get_metric_statistics(
        Namespace='HotWater',
        MetricName='liter_deficit',
        StartTime=starttime,
        EndTime=endtime,
        Period=10, # seconds, must be multiple of 60
        Statistics=[
            'Maximum'
        ],
    )
    
    print(response['Datapoints'])
    
    liter_deficit = response['Datapoints'][0]['Maximum']
    print("Liters Unheated: {0}".format(liter_deficit))
    
    # calcualte gallons heated
    liters_remaining = capacity_liters + liter_deficit # liter_deficit is negative
    gallons_remaining = liters_remaining * 0.264172
    
    shower_minutes = math.floor(liters_remaining / shower_liters_per_minute) #8.4 liters per minute
        
    speech_output = "You can shower for {:d} minutes.".format(shower_minutes)

    return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, "", should_end_session))


def water_remaining(intent, session):
    """Return water remaining.
    """

    card_title = "Water Remaining"
    session_attributes = {}
    should_end_session = session['new']

    usertimezone = timezone('US/Mountain')
    endtime = datetime.now(usertimezone)
    starttime = endtime - timedelta(minutes=2)
    

    #query cloudwatch for liters used.
    response = cloudwatch_client.get_metric_statistics(
        Namespace='HotWater',
        MetricName='liter_deficit',
        StartTime=starttime,
        EndTime=endtime,
        Period=10, # seconds, must be multiple of 60
        Statistics=[
            'Maximum'
        ],
    )
    
    print(response['Datapoints'])
    
    liter_deficit = response['Datapoints'][0]['Maximum']
    print("Liters Unheated: {0}".format(liter_deficit))
    
    # calcualte gallons heated
    liters_remaining = capacity_liters + liter_deficit # liter_deficit is negative
    gallons_remaining = liters_remaining * 0.264172
    
    # calculate percentage heated
    percentage_remaining = (gallons_remaining / capacity_gallons) * 100
    
    #convert to gallons (todo: add preference.)
        
    if liter_deficit == 0:
        speech_output = "Your hot water is fully heated. "
    else:
        speech_output = "You have {:3.0f} percent remaining, or {:3.0f} gallons of hot water. ".format(percentage_remaining, gallons_remaining) 
    

    return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, "", should_end_session))



def water_volume_used(intent, session):
    """ Reports on water used on arbitrary times.
    """

    card_title = "Water Volume"
    session_attributes = {}
    should_end_session = session['new']
    
    #intent will have EITHER period or timeframe
    usertimezone = timezone('US/Mountain')
    
    # period: today, yesterday, this week, last week. defaults to today
    if 'period' in intent['slots'] and 'value' in intent['slots']['period']:
        period = intent['slots']['period']['value']
        phrase = period
        if period == 'today':
            starttime = datetime.now(usertimezone).replace(hour=0,minute=0,second=0,microsecond=0)
            endtime = starttime + timedelta(hours=24)
        elif period == 'yesterday':
            starttime = datetime.now(usertimezone).replace(hour=0,minute=0,second=0,microsecond=0)
            starttime = starttime - timedelta(hours=24)
            endtime = starttime + timedelta(hours=24)
        elif period == 'this week':
            starttime = datetime.now(usertimezone).replace(hour=0,minute=0,second=0,microsecond=0)
            days_to_start_of_week = starttime.weekday()
            starttime = starttime - timedelta(days=days_to_start_of_week)
            endtime = starttime + timedelta(days=7)
        elif period == 'last week':
            starttime = datetime.now(usertimezone).replace(hour=0,minute=0,second=0,microsecond=0)
            days_to_start_of_week = starttime.weekday() + 7
            starttime = starttime - timedelta(days=days_to_start_of_week)
            endtime = starttime + timedelta(days=7)
        else:
            print("unknown period: {0}. Try today or yesterday.".format(period))
        

    if 'timeframe' in intent['slots'] and 'value' in intent['slots']['timeframe']: 
        timeframe = intent['slots']['timeframe']['value']
        duration = isodate.parse_duration(timeframe)
        
        # create phrase from timeframe. 
        #pick apart with regex
        duration_regex = re.compile("^P(?!$)((?P<year>\d+)Y)?((?P<month>\d+)M)?((?P<week>\d+)W)?((?P<day>\d+)D)?(T(?=\d)((?P<hour>\d+)H)?((?P<minute>\d+)M)?((?P<second>\d+)S)?)?$")
        d_matches = duration_regex.search(timeframe).groupdict()
        d_phrase_list = [] #timeframe
        for t in ["year","month","week","day","hour","minute","second"]:
            if t in d_matches and d_matches[t] is not None: 
                d_phrase_list.append("{0} {1}{2}".format(d_matches[t], t, "s" if int(d_matches[t])>1 else ""))
        d_phrase = " ".join(d_phrase_list)
            
        endtime = datetime.now(usertimezone)
        starttime = endtime - duration
        phrase = "in the last {0}".format(d_phrase)
        
    #extract duration information from timeframe
    
    #construct starttime and endtime
    print("Query Start Time: {0}".format(starttime))
    print("Query End Time: {0}".format(endtime))
    
    #query cloudwatch for liters used.
    response = cloudwatch_client.get_metric_statistics(
        Namespace='HotWater',
        MetricName='liters_used',
        StartTime=starttime,
        EndTime=endtime,
        Period=60*60*24*365, # seconds, must be multiple of 60
        Statistics=[
            'Sum'
        ],
    )
    
    liters = response['Datapoints'][0]['Sum']
    print("Liters: {0}".format(liters))
    
    gallons = liters * 0.264172
    
    #convert to gallons (todo: add preference.)
        
    if gallons == 0:
        speech_output = "You have used no hot water {0}. ".format(phrase) 
    else:
        speech_output = "You have used {0:0.1f} gallons of hot water {1}. ".format(gallons, phrase) 
    
    reprompt_text = "I'm not sure what that timeframe is. " \
                    "A valid timeframe is something like 6 hours, 3 days, or 10 minutes. "
    return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, reprompt_text, should_end_session))

# --------------- Events ------------------

def on_session_started(session_started_request, session):
    """ Called when the session starts """

    print("on_session_started requestId=" + session_started_request['requestId']
          + ", sessionId=" + session['sessionId'])


def on_launch(launch_request, session):
    """ Called when the user launches the skill without specifying what they
    want
    """

    print("on_launch requestId=" + launch_request['requestId'] +
          ", sessionId=" + session['sessionId'])
    # Dispatch to your skill's launch
    return get_welcome_response()


def on_intent(intent_request, session):
    """ Called when the user specifies an intent for this skill """

    print("on_intent requestId=" + intent_request['requestId'] +
          ", sessionId=" + session['sessionId'])

    intent = intent_request['intent']
    intent_name = intent_request['intent']['name']

    # Dispatch to your skill's intent handlers
    if intent_name == "WaterVolumeUsed":
        return water_volume_used(intent, session)
    elif intent_name == "WaterRemaining":
        return water_remaining(intent, session)
    elif intent_name == "LengthOfShower":
        return length_of_shower(intent, session)
    elif intent_name == "AMAZON.HelpIntent":
        return get_welcome_response()
    elif intent_name == "AMAZON.CancelIntent" or intent_name == "AMAZON.StopIntent":
        return handle_session_end_request()
    else:
        raise ValueError("Invalid intent")


def on_session_ended(session_ended_request, session):
    """ Called when the user ends the session.

    Is not called when the skill returns should_end_session=true
    """
    print("on_session_ended requestId=" + session_ended_request['requestId'] +
          ", sessionId=" + session['sessionId'])
    # add cleanup logic here


# --------------- Main handler ------------------

def lambda_handler(event, context):
    """ Route the incoming request based on type (LaunchRequest, IntentRequest,
    etc.) The JSON body of the request is provided in the event parameter.
    """
    print("event.session.application.applicationId=" +
          event['session']['application']['applicationId'])

    if event['session']['new']:
        on_session_started({'requestId': event['request']['requestId']}, event['session'])

    if event['request']['type'] == "LaunchRequest":
        return on_launch(event['request'], event['session'])
    elif event['request']['type'] == "IntentRequest":
        return on_intent(event['request'], event['session'])
    elif event['request']['type'] == "SessionEndedRequest":
        return on_session_ended(event['request'], event['session'])
