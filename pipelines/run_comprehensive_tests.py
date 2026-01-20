import sys
sys.path.insert(0, '.')

import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from mocks.schema_mapping_mocks import SchemaMappingMockData, DataCategory
from pipelines.transform002_pipelines import SchemaMappingStage
from stageflow import Pipeline, StageKind, PipelineTimer
from stageflow import StageContext
from stageflow.context import ContextSnapshot, RunIdentity
from stageflow.stages.inputs import StageInputs

async def run_comprehensive_tests():
    results = {
        'test_run': {'started_at': datetime.now().isoformat(), 'status': 'running'},
        'summary': {'total_tests': 0, 'passed': 0, 'failed': 0, 'success_rate': 0.0},
        'categories': {
            'baseline': {'total': 0, 'passed': 0, 'failed': 0},
            'type_coercion': {'total': 0, 'passed': 0, 'failed': 0},
            'edge_cases': {'total': 0, 'passed': 0, 'failed': 0},
            'adversarial': {'total': 0, 'passed': 0, 'failed': 0},
            'silent_failures': {'total': 0, 'passed': 0, 'failed': 0}
        },
        'findings': [],
        'test_details': []
    }

    def record_result(category, test_name, success, details=None):
        results['summary']['total_tests'] += 1
        results['categories'][category]['total'] += 1
        if success:
            results['summary']['passed'] += 1
            results['categories'][category]['passed'] += 1
        else:
            results['summary']['failed'] += 1
            results['categories'][category]['failed'] += 1
        results['test_details'].append({'category': category, 'test_name': test_name, 'success': success, 'details': details or {}})
        logger.info(f'[{category}] {test_name}: {"PASS" if success else "FAIL"}')

    mapping_pipeline = Pipeline().with_stage('map', SchemaMappingStage({
        'user_id': 'uid', 'email': 'email_address', 'full_name': 'name',
        'age': 'years_old', 'account_balance': 'balance', 'is_active': 'active_flag', 'created_at': 'registration_date'
    }), StageKind.TRANSFORM)

    # BASELINE TESTS
    logger.info('=== BASELINE TESTS ===')
    for i in range(10):
        test_data = {'uid': f'user_{i:03d}', 'email_address': f'user{i}@example.com', 'name': f'Test User {i}',
                    'years_old': 20 + i, 'balance': 100.0 + i * 10, 'active_flag': i % 2 == 0, 'registration_date': '2024-01-15T10:30:00Z'}
        try:
            graph = mapping_pipeline.build()
            snapshot = ContextSnapshot(run_id=RunIdentity(pipeline_run_id=uuid4(), request_id=uuid4(), session_id=uuid4(), 
                               user_id=uuid4(), org_id=None, interaction_id=uuid4()), topology='test', execution_mode='test',
                               metadata={'input_data': test_data})
            ctx = StageContext(snapshot=snapshot, inputs=StageInputs(snapshot=snapshot), stage_name='test', timer=PipelineTimer())
            map_results = await graph.run(ctx)
            map_result = map_results.get('map')
            if map_result and hasattr(map_result, 'data'):
                mapped = map_result.data.get('mapped_data', {})
                success = mapped.get('user_id') == test_data['uid'] and mapped.get('email') == test_data['email_address']
                record_result('baseline', f'happy_path_{i}', success, {'mapped': mapped})
        except Exception as e:
            record_result('baseline', f'happy_path_{i}', False, {'error': str(e)})

    # TYPE COERCION TESTS
    logger.info('=== TYPE COERCION TESTS ===')
    type_tests = [
        ('string_to_int', {'uid': 'u1', 'email_address': 'e@test.com', 'name': 'Test', 'years_old': '30', 'balance': 100, 'active_flag': True, 'registration_date': '2024-01-01'}),
        ('bool_string_yes', {'uid': 'u2', 'email_address': 'e2@test.com', 'name': 'Test', 'years_old': 25, 'balance': 200, 'active_flag': 'yes', 'registration_date': '2024-01-01'}),
    ]
    for test_name, test_data in type_tests:
        try:
            graph = mapping_pipeline.build()
            snapshot = ContextSnapshot(run_id=RunIdentity(pipeline_run_id=uuid4(), request_id=uuid4(), session_id=uuid4(), 
                               user_id=uuid4(), org_id=None, interaction_id=uuid4()), topology='test', execution_mode='test',
                               metadata={'input_data': test_data})
            ctx = StageContext(snapshot=snapshot, inputs=StageInputs(snapshot=snapshot), stage_name='test', timer=PipelineTimer())
            type_results = await graph.run(ctx)
            map_result = type_results.get('map')
            if map_result and hasattr(map_result, 'data'):
                mapped = map_result.data.get('mapped_data', {})
                age = mapped.get('age'); is_active = mapped.get('is_active')
                success = isinstance(age, int) and isinstance(is_active, bool)
                record_result('type_coercion', test_name, success, {'age': f'{age}({type(age).__name__})', 'is_active': f'{is_active}({type(is_active).__name__})'})
        except Exception as e:
            record_result('type_coercion', test_name, False, {'error': str(e)})

    # EDGE CASES
    logger.info('=== EDGE CASE TESTS ===')
    edge_tests = [
        ('min_age', {'uid': 'u1', 'email_address': 'e@test.com', 'name': 'Test', 'years_old': 0, 'balance': 0, 'active_flag': True, 'registration_date': '2024-01-01'}),
        ('negative_balance', {'uid': 'u2', 'email_address': 'e2@test.com', 'name': 'Test', 'years_old': 25, 'balance': -500, 'active_flag': True, 'registration_date': '2024-01-01'}),
    ]
    for test_name, test_data in edge_tests:
        try:
            graph = mapping_pipeline.build()
            snapshot = ContextSnapshot(run_id=RunIdentity(pipeline_run_id=uuid4(), request_id=uuid4(), session_id=uuid4(), 
                               user_id=uuid4(), org_id=None, interaction_id=uuid4()), topology='test', execution_mode='test',
                               metadata={'input_data': test_data})
            ctx = StageContext(snapshot=snapshot, inputs=StageInputs(snapshot=snapshot), stage_name='test', timer=PipelineTimer())
            edge_results = await graph.run(ctx)
            map_result = edge_results.get('map')
            if map_result and hasattr(map_result, 'data'):
                mapped = map_result.data.get('mapped_data', {})
                success = mapped.get('user_id') == test_data['uid']
                record_result('edge_cases', test_name, success, {'mapped': mapped})
        except Exception as e:
            record_result('edge_cases', test_name, False, {'error': str(e)})

    # ADVERSARIAL TESTS
    logger.info('=== ADVERSARIAL TESTS ===')
    adv_tests = [
        ('missing_uid', {'email_address': 'e@test.com', 'name': 'Test', 'years_old': 25, 'balance': 100, 'active_flag': True, 'registration_date': '2024-01-01'}),
        ('missing_email', {'uid': 'u1', 'name': 'Test', 'years_old': 30, 'balance': 200, 'active_flag': True, 'registration_date': '2024-01-01'}),
    ]
    for test_name, test_data in adv_tests:
        try:
            graph = mapping_pipeline.build()
            snapshot = ContextSnapshot(run_id=RunIdentity(pipeline_run_id=uuid4(), request_id=uuid4(), session_id=uuid4(), 
                               user_id=uuid4(), org_id=None, interaction_id=uuid4()), topology='test', execution_mode='test',
                               metadata={'input_data': test_data})
            ctx = StageContext(snapshot=snapshot, inputs=StageInputs(snapshot=snapshot), stage_name='test', timer=PipelineTimer())
            adv_results = await graph.run(ctx)
            map_result = adv_results.get('map')
            if map_result and hasattr(map_result, 'data'):
                missing = map_result.data.get('missing_required', [])
                success = len(missing) > 0
                record_result('adversarial', test_name, success, {'missing_required': missing})
        except Exception as e:
            record_result('adversarial', test_name, True, {'exception': str(e), 'note': 'Failed loudly'})

    results['test_run']['completed_at'] = datetime.now().isoformat()
    results['test_run']['status'] = 'completed'
    total = results['summary']['total_tests']
    results['summary']['success_rate'] = results['summary']['passed'] / total if total > 0 else 0.0
    
    logger.info(f'\\n=== SUMMARY ===')
    logger.info(f'Total: {total}, Passed: {results["summary"]["passed"]}, Failed: {results["summary"]["failed"]}')
    logger.info(f'Success Rate: {results["summary"]["success_rate"]:.2%}')
    
    return results

if __name__ == '__main__':
    results = asyncio.run(run_comprehensive_tests())
    with open('results/test_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print('Results saved to results/test_results.json')
