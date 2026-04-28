# coding=utf8

# TODO
# 1. Preserve API endpoints: inspection, alert, release
# 2. Preserve directories under app/business/: ad, search, reco
# 3. Add app/knowledge/ directory for service-related knowledge
# 4. Comment data fetch code flow, prompt users to implement their own data fetching

import logging
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

import time
import traceback
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from flask import Flask, request, make_response
import atexit

from app.skill_explore.skill_explore_main import run_inspect, run_release, run_warning
from app.skill_explore.skill_feedback import run_skill_feedback_new
from app.util.logger import error_log, business_log, save_raw_request, setup_logging

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # Disable ASCII conversion, keep original characters

setup_logging(app)
logging.basicConfig(filename='app.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

executor = ThreadPoolExecutor(max_workers=8)
atexit.register(lambda: executor.shutdown(wait=False))


def create_response(data, status=200):
    """Create standardized JSON response"""
    if isinstance(data, dict):
        response = make_response(json.dumps(data, ensure_ascii=False))
    else:
        response = make_response(data)
    response.status_code = status
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response


@app.route("/alert", methods=['POST'])
def alert():
    """
    Alert analysis entry point.
    """
    request_id = save_raw_request(req=request, need_dump=False)
    business_log(f"request_id: {request_id}, get warning request succ")

    try:
        if request.method != 'POST':
            return create_response({"error": "Method not allowed", "message": "Only POST method is supported"}, 405)

        data = request.get_json()
        if not data:
            raise ValueError("No JSON data received")

        business_log(f"request_id: {request_id}, warning get data succ")

        try:
            result = run_warning(data=data, request_id=request_id)

            return create_response(result, 200)

        except Exception as e:
            error_log(f"request_id:{request_id} execution error: {traceback.format_exc()}")
            return create_response({
                "error": "Internal server error",
                "message": str(e)
            }, 500)

    except Exception as e:
        error_log(f"request_id: {request_id}, unexpected exception: {traceback.format_exc()}")
        return create_response({"error": "internal server error", "message": str(e)}, 500)

@app.route("/inspection", methods=['POST'])
def inspection():
    request_id = save_raw_request(req=request, need_dump=False)
    business_log(f"request_id: {request_id}, get inspection request succ")

    try:
        if request.method != 'POST':
            return create_response({"error": "Method not allowed", "message": "Only POST method is supported"}, 405)

        data = request.get_json()
        if not data:
            raise ValueError("No JSON data received")
        try:
            biz = data.get("biz", "")
            if biz == "":
                raise ValueError("biz is required")
            
            rule_id = data.get("rule_id", "")
            if rule_id == "":
                raise ValueError("rule_id is required")
            
            timestamp = data.get("timestamp", int(time.time()))
            
            result = run_inspect(biz=biz, rule_id=rule_id, request_id=request_id, timestamp=timestamp)

            return create_response(result, 200)

        except Exception as e:
            error_log(f"request_id:{request_id} execution error: {traceback.format_exc()}")
            return create_response({
                "error": "Internal server error",
                "message": str(e)
            }, 500)

    except Exception as e:
        error_log(f"request_id: {request_id}, unexpected exception: {traceback.format_exc()}")
        return create_response({"error": "internal server error", "message": str(e)}, 500)

@app.route("/release", methods=['POST'])
def release():
    request_id = save_raw_request(req=request, need_dump=False)
    business_log(f"request_id: {request_id}, get warning request succ")

    try:
        if request.method != 'POST':
            return create_response({"error": "Method not allowed", "message": "Only POST method is supported"}, 405)

        data = request.get_json()
        if not data:
            raise ValueError("No JSON data received")
        try:
            result = run_release(data=data, request_id=request_id)
            return create_response(result, 200)

        except Exception as e:
            error_log(f"request_id:{request_id} execution error: {traceback.format_exc()}")
            return create_response({
                "error": "Internal server error",
                "message": str(e)
            }, 500)

    except Exception as e:
        error_log(f"request_id: {request_id}, unexpected exception: {traceback.format_exc()}")
        return create_response({"error": "internal server error", "message": str(e)}, 500)

@app.route('/feedback', methods=['POST'])
def feedback():
    # Async feedback endpoint
    # Get business type from URL parameters
    request_id = save_raw_request(request)
    try:
        scene_id = request.form.get('feedback_scene', '')
        data_changes = request.form.get('data_changes', '')
        prompt_changes = request.form.get('prompt_changes', '')
        biz_list = request.form.getlist('biz_list')

        ret = run_skill_feedback_new(scene_id=scene_id, biz_list=biz_list, data_changes=data_changes, prompt=prompt_changes, request_id=request_id)
        if ret is None or not ret.success:
            msg = ret.message if ret is not None else "feedback failed, please check logs"
            return create_response({"error": "feedback failed", "message": msg}, 500)

        return create_response({"success": True, "message": "Feedback submitted successfully"}, 200)
    except Exception as e:
        error_log(f"request_id: {request_id}, unexpected exception: {traceback.format_exc()}")
        return create_response({"error": "internal server error", "message": str(e)}, 500)

@app.route("/health")
def health_check():
    """Service health check"""
    return "ok"

if __name__ == '__main__':
    app.run(threaded=True)